# --- File: kasa/views.py ---

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseBadRequest
from django.db import transaction, models
from django.urls import reverse
from django.db.models import Sum, Q, Min, Max, F # F eklendi
from django.contrib import messages
from django.utils import timezone

# Modelleri ve formu import et
from .models import (Case, Skin, UserProfile, CaseSkin, UserInventoryItem, UpgradeAttempt,
                     CaseBattle, CaseBattleParticipant, CaseBattleUnboxing, Rarity)
from .forms import CreateCaseBattleForm

import random
import decimal
import json

# --- Temel View'lar ---
def home(request):
    active_cases = Case.objects.filter(is_active=True)
    context = {'cases': active_cases}
    return render(request, 'kasalar.html', context)

def case_detail(request, case_id):
    case = get_object_or_404(Case, pk=case_id, is_active=True)
    possible_skins = CaseSkin.objects.filter(case=case).select_related('skin', 'skin__rarity').order_by('-probability')
    ajax_open_url = reverse('open_case_ajax', args=[case.id])
    context = { 'case': case, 'possible_skins': possible_skins, 'ajax_open_url': ajax_open_url }
    return render(request, 'kasa-ac.html', context)

@login_required
def profile(request):
    try: user_profile = request.user.profile
    except UserProfile.DoesNotExist: messages.error(request,"Profil bulunamadı."); return redirect('home')
    inventory_items = UserInventoryItem.objects.filter(user_profile=user_profile, status=UserInventoryItem.ItemStatus.AVAILABLE).select_related('skin', 'skin__rarity')
    trade_url_update_url = reverse('update_trade_url_ajax')
    context = { 'profile': user_profile, 'inventory': inventory_items, 'trade_url_update_url': trade_url_update_url }
    return render(request, 'kazanilan_skinler.html', context)

@login_required
def deposit_page(request): return render(request, 'bakiye_ekle.html', {})

@login_required
def withdraw_page(request): return redirect('profile')

@login_required
def upgrade_page(request):
    user_profile = get_object_or_404(UserProfile, user=request.user); user_inventory = UserInventoryItem.objects.filter(user_profile=user_profile, status=UserInventoryItem.ItemStatus.AVAILABLE).select_related('skin', 'skin__rarity').order_by('-skin__value'); owned_skin_ids = user_inventory.values_list('skin_id', flat=True); potential_targets = Skin.objects.filter(value__gt=0).exclude(id__in=owned_skin_ids).select_related('rarity').order_by('value'); calculate_url = reverse('calculate_upgrade_ajax'); perform_url = reverse('perform_upgrade_ajax'); context = { 'inventory': user_inventory, 'potential_targets': potential_targets, 'calculate_url': calculate_url, 'perform_url': perform_url, 'profile': user_profile }; return render(request, 'upgrade.html', context)

# --- AJAX View'ları ---
@login_required
@transaction.atomic
def open_case_ajax(request, case_id):
    # ... (önceki gibi) ...
    if request.method != 'POST': return HttpResponseBadRequest()
    case = get_object_or_404(Case, pk=case_id, is_active=True); user_profile = get_object_or_404(UserProfile, user=request.user); case_price = decimal.Decimal(case.price)
    if user_profile.balance < case_price: return JsonResponse({'success': False, 'error': 'Yetersiz bakiye!'})
    case_skins_data = CaseSkin.objects.filter(case=case).select_related('skin','skin__rarity')
    if not case_skins_data.exists(): return JsonResponse({'success': False, 'error': 'Kasada eşya yok!'})
    skins = [cs.skin for cs in case_skins_data]; probabilities = [cs.probability for cs in case_skins_data]; total_prob = sum(probabilities)
    if not (0.99 < total_prob < 1.01): print(f"Uyarı: Kasa ID {case.id} prob toplamı {total_prob}!")
    try: won_skin = random.choices(skins, weights=probabilities, k=1)[0]
    except (IndexError, ValueError) as e: print(f"Hata: random.choices - {e}. Kasa ID: {case.id}"); return JsonResponse({'success': False, 'error': 'Skin seçimi hatası.'})
    user_profile.balance -= case_price; user_profile.save()
    reel_length = 50; reel_items_data = []; possible_reel_skins = list(case_skins_data)
    for _ in range(reel_length - 1): chosen_cs = random.choice(possible_reel_skins); reel_items_data.append({'id': chosen_cs.skin.id, 'name': chosen_cs.skin.name, 'image_url': chosen_cs.skin.image_url or '', 'rarity_color': chosen_cs.skin.rarity.color_hex if chosen_cs.skin.rarity else '#FFFFFF'})
    winner_index = 40; reel_items_data.insert(winner_index, {'id': won_skin.id, 'name': won_skin.name, 'image_url': won_skin.image_url or '', 'rarity_color': won_skin.rarity.color_hex if won_skin.rarity else '#FFFFFF'})
    UserInventoryItem.objects.create(user_profile=user_profile, skin=won_skin, status=UserInventoryItem.ItemStatus.AVAILABLE)
    return JsonResponse({'success': True, 'reel_items': reel_items_data, 'winner_index': winner_index, 'won_skin': {'name': won_skin.name, 'image_url': won_skin.image_url or '', 'rarity_name': won_skin.rarity.name if won_skin.rarity else 'N/A', 'rarity_color': won_skin.rarity.color_hex if won_skin.rarity else '#FFFFFF'}, 'new_balance': user_profile.balance})


@login_required
def update_trade_url_ajax(request):
    # ... (önceki gibi) ...
    if request.method == 'POST':
        new_trade_url = request.POST.get('trade_url', '').strip()
        if not new_trade_url or not new_trade_url.startswith('https://steamcommunity.com/tradeoffer/new/'): return JsonResponse({'success': False, 'error': 'Geçersiz URL.'})
        try: profile = request.user.profile; profile.trade_url = new_trade_url; profile.save(); return JsonResponse({'success': True, 'message': 'URL güncellendi.'})
        except UserProfile.DoesNotExist: return JsonResponse({'success': False, 'error': 'Profil bulunamadı.'})
        except Exception as e: print(f"Trade URL error: {e}"); return JsonResponse({'success': False, 'error': 'Güncellenemedi.'})
    return HttpResponseBadRequest()

def calculate_upgrade_chance(input_val, target_val):
    # ... (önceki gibi) ...
    if target_val <= 0 or input_val <= 0: return 0.0
    ratio = float(input_val / target_val); multiplier = 0.85; chance = ratio * multiplier; return max(0.01, min(chance, 0.90))

@login_required
def calculate_upgrade_ajax(request):
    # ... (önceki gibi) ...
    if request.method != 'POST': return HttpResponseBadRequest()
    try: data = json.loads(request.body); input_ids = data.get('input_item_ids', []); target_id = data.get('target_skin_id')
    except json.JSONDecodeError: return JsonResponse({'success': False, 'error': 'Geçersiz istek.'})
    if not input_ids or not target_id: return JsonResponse({'success': False, 'error': 'Girdi/hedef seçilmedi.'})
    try: profile = request.user.profile; items = UserInventoryItem.objects.filter(user_profile=profile, id__in=input_ids, status=UserInventoryItem.ItemStatus.AVAILABLE).select_related('skin')
    except UserProfile.DoesNotExist: return JsonResponse({'success': False, 'error': 'Profil bulunamadı.'})
    if len(input_ids) != items.count(): return JsonResponse({'success': False, 'error': 'Eşyalar geçersiz.'})
    input_val = items.aggregate(total=Sum('skin__value'))['total'] or decimal.Decimal('0.00')
    try: target = Skin.objects.get(pk=target_id)
    except Skin.DoesNotExist: return JsonResponse({'success': False, 'error': 'Hedef bulunamadı.'})
    chance = calculate_upgrade_chance(input_val, target.value); return JsonResponse({'success': True, 'chance': round(chance * 100, 2), 'total_input_value': input_val, 'target_skin_value': target.value})


@login_required
@transaction.atomic
def perform_upgrade_ajax(request):
    # ... (önceki gibi) ...
    if request.method != 'POST': return HttpResponseBadRequest()
    try: data = json.loads(request.body); input_ids = data.get('input_item_ids', []); target_id = data.get('target_skin_id')
    except json.JSONDecodeError: return JsonResponse({'success': False, 'error': 'Geçersiz istek.'})
    if not input_ids or not target_id: return JsonResponse({'success': False, 'error': 'Girdi/hedef seçilmedi.'})
    try: profile = request.user.profile; target = Skin.objects.get(pk=target_id)
    except (UserProfile.DoesNotExist, Skin.DoesNotExist): return JsonResponse({'success': False, 'error': 'Profil/hedef bulunamadı.'})
    items = UserInventoryItem.objects.select_for_update().filter(user_profile=profile, id__in=input_ids, status=UserInventoryItem.ItemStatus.AVAILABLE).select_related('skin')
    if len(input_ids) != items.count() or not items.exists(): return JsonResponse({'success': False, 'error': 'Eşyalar geçersiz/kullanımda.'})
    input_val = items.aggregate(total=Sum('skin__value'))['total'] or decimal.Decimal('0.00')
    chance = calculate_upgrade_chance(input_val, target.value); rolled = random.random(); success = rolled < chance
    try: updated = items.update(status=UserInventoryItem.ItemStatus.USED_UPGRADE); assert updated == len(input_ids)
    except Exception as e: print(f"Upgrade item status update failed: {e}"); raise
    UpgradeAttempt.objects.create(user_profile=profile, input_value=input_val, target_skin=target, target_value=target.value, success_chance=chance, rolled_number=rolled, was_successful=success)
    outcome_str = 'successful' if success else 'failed'
    if success: UserInventoryItem.objects.create(user_profile=profile, skin=target, status=UserInventoryItem.ItemStatus.AVAILABLE); return JsonResponse({'success': True, 'outcome': outcome_str, 'message': f'Tebrikler! {target.name} kazandınız!', 'won_skin': { 'name': target.name, 'image_url': target.image_url or '', 'rarity_name': target.rarity.name if target.rarity else 'N/A', 'rarity_color': target.rarity.color_hex if target.rarity else '#FFFFFF'}, 'chance': round(chance * 100, 2), 'rolled': round(rolled * 100, 2)})
    else: return JsonResponse({'success': True, 'outcome': outcome_str, 'message': 'Yükseltme başarısız.', 'chance': round(chance * 100, 2), 'rolled': round(rolled * 100, 2)})

# --- Kasa Savaşları View'ları ---
@login_required
def active_battles_list(request):
    # ... (önceki gibi) ...
    battles = CaseBattle.objects.filter(status=CaseBattle.BattleStatus.WAITING).select_related('creator__user').prefetch_related('participants', 'cases').order_by('-created_at')
    context = {'battles': battles}
    return render(request, 'active_battles.html', context)

@login_required
@transaction.atomic
def create_battle(request):
    # ... (önceki gibi) ...
    if request.method == 'POST':
        form = CreateCaseBattleForm(request.POST)
        if form.is_valid():
            try: user_profile = request.user.profile; selected_cases = form.cleaned_data['cases']; mode = form.cleaned_data['mode']; max_participants = int(form.cleaned_data['max_participants']); total_cost = sum(case.price for case in selected_cases)
            except UserProfile.DoesNotExist: messages.error(request,"Profil bulunamadı."); context={'form': form}; return render(request, 'create_battle.html', context)
            if user_profile.balance < total_cost: messages.error(request, f"Yetersiz bakiye! Gerekli: {total_cost}₺")
            else:
                try:
                    user_profile.balance -= total_cost; user_profile.save()
                    new_battle = CaseBattle.objects.create(creator=user_profile, mode=mode, max_participants=max_participants)
                    new_battle.cases.set(selected_cases)
                    CaseBattleParticipant.objects.create(battle=new_battle, user_profile=user_profile, is_bot=False)
                    messages.success(request, "Savaş başarıyla oluşturuldu!")
                    return redirect('battle_detail', battle_id=new_battle.id)
                except Exception as e: print(f"Savaş oluşturma hatası: {e}"); messages.error(request, "Savaş oluşturulurken hata oluştu.")
        else: messages.error(request, "Lütfen formdaki hataları düzeltin.")
        context = {'form': form}; return render(request, 'create_battle.html', context)
    else: form = CreateCaseBattleForm(); context = {'form': form}; return render(request, 'create_battle.html', context)


@login_required
def battle_detail(request, battle_id):
    # ... (önceki gibi, value_per_participant ve col_lg_class_value hesaplamaları dahil) ...
     battle = get_object_or_404( CaseBattle.objects.select_related('creator__user').prefetch_related('participants__user_profile__user', 'cases', 'participants__unboxings__unboxed_skin__rarity'), pk=battle_id)
     is_creator = False; is_participant = False; user_profile = None
     if hasattr(request.user, 'profile'):
        try: user_profile = request.user.profile; is_creator = battle.creator == user_profile if battle.creator else False; is_participant = battle.participants.filter(user_profile=user_profile).exists()
        except UserProfile.DoesNotExist: pass
     can_join = battle.is_joinable() and not is_participant
     can_add_bot = is_creator and battle.is_joinable()
     winners = battle.participants.filter(is_winner=True)
     multiple_winners = winners.count() > 1
     value_per_participant = None
     col_lg_class_value = 6
     if battle.status == CaseBattle.BattleStatus.FINISHED and battle.mode == CaseBattle.BattleMode.SHARED:
        real_participant_count = battle.get_real_participant_count()
        if real_participant_count > 0:
            try: value_per_participant = (battle.total_value / decimal.Decimal(real_participant_count)).quantize(decimal.Decimal("0.01"), rounding=decimal.ROUND_DOWN)
            except decimal.InvalidOperation: value_per_participant = 0; print(f"Hata: Savaş #{battle.id} Ortak mod değer hesaplama.")
     participant_count = battle.get_participant_count()
     if participant_count == 3: col_lg_class_value = 4
     elif participant_count >= 4: col_lg_class_value = 3
     elif participant_count == 1: col_lg_class_value = 12
     context = { 'battle': battle, 'is_creator': is_creator, 'is_participant': is_participant, 'can_join': can_join, 'can_add_bot': can_add_bot, 'winners': winners, 'multiple_winners': multiple_winners, 'value_per_participant': value_per_participant, 'col_lg_class_value': col_lg_class_value, }
     return render(request, 'battle_detail.html', context)


# --- Savaş Başlatma Mantığı (DÜZELTİLMİŞ - messages.info kaldırıldı) ---
def _perform_single_unboxing(case: Case) -> Skin | None:
    # ... (içerik aynı) ...
    case_skins_data = CaseSkin.objects.filter(case=case).select_related('skin')
    if not case_skins_data.exists(): return None
    skins = [cs.skin for cs in case_skins_data]; probabilities = [cs.probability for cs in case_skins_data]; total_prob = sum(probabilities)
    if not (0.99 < total_prob < 1.01): print(f"Uyarı: Kasa ID {case.id} prob {total_prob}!");
    try: return random.choices(skins, weights=probabilities, k=1)[0] if skins and probabilities else None
    except (IndexError, ValueError) as e: print(f"Hata: _perform_unboxing - {e}. Kasa ID: {case.id}"); return None

@transaction.atomic
def start_battle_logic(battle: CaseBattle):
    print(f"!!! Savaş #{battle.id} BAŞLATILIYOR... (Mod: {battle.mode})")
    if battle.status != CaseBattle.BattleStatus.WAITING: print(f"Uyarı: Savaş #{battle.id} zaten başlatılmış/bitmiş."); return

    battle.status = CaseBattle.BattleStatus.STARTING
    battle.started_at = timezone.now()
    battle.save(update_fields=['status', 'started_at'])

    try:
        participant_totals = {}
        participants = list(battle.participants.select_related('user_profile__user').all())
        unboxings_to_create = []
        all_unboxed_skins_pks = []

        # 1. Kasaları Aç
        for participant in participants:
            participant_total = decimal.Decimal('0.00')
            for case in battle.cases.all():
                won_skin = _perform_single_unboxing(case)
                if won_skin:
                    unboxings_to_create.append(CaseBattleUnboxing(battle_participant=participant, case=case, unboxed_skin=won_skin))
                    participant_total += won_skin.value
                    all_unboxed_skins_pks.append(won_skin.pk)
                else: print(f"Uyarı: Savaş #{battle.id}, P:{participant.id}, C:{case.name} açılamadı.")
            participant.total_unboxed_value = participant_total
            if not participant.is_bot and participant.user_profile: participant_totals[participant.id] = participant_total

        if unboxings_to_create: CaseBattleUnboxing.objects.bulk_create(unboxings_to_create)

        # 2. Toplam Değer
        battle.total_value = sum(p.total_unboxed_value for p in participants)

        # 3. Kazananı Belirle
        winners = []; losers = []; real_participants = [p for p in participants if not p.is_bot and p.user_profile]
        if real_participants:
            valid_totals = {p.id: p.total_unboxed_value for p in real_participants}
            if battle.mode == CaseBattle.BattleMode.STANDARD:
                 if valid_totals: max_value = max(valid_totals.values()); winners_ids = {pid for pid, val in valid_totals.items() if val == max_value}; winners = [p for p in real_participants if p.id in winners_ids]; losers = [p for p in real_participants if p.id not in winners_ids]
            elif battle.mode == CaseBattle.BattleMode.UNDERDOG:
                 if valid_totals: min_value = min(valid_totals.values()); winners_ids = {pid for pid, val in valid_totals.items() if val == min_value}; winners = [p for p in real_participants if p.id in winners_ids]; losers = [p for p in real_participants if p.id not in winners_ids]
            elif battle.mode == CaseBattle.BattleMode.SHARED: winners = real_participants

        # Kazananları ve değerleri topluca güncelle
        for p in participants: p.is_winner = (p in winners)
        CaseBattleParticipant.objects.bulk_update(participants, ['total_unboxed_value', 'is_winner'])

        # 4. Ödülleri Dağıt
        consolation_skin = None
        if losers and (battle.mode == CaseBattle.BattleMode.STANDARD or battle.mode == CaseBattle.BattleMode.UNDERDOG):
             consolation_skin = Skin.objects.filter(value__gt=0, value__lt=5).order_by('?').first()

        if winners:
            if battle.mode == CaseBattle.BattleMode.STANDARD or battle.mode == CaseBattle.BattleMode.UNDERDOG:
                if len(winners) == 1:
                    winner_profile = winners[0].user_profile
                    new_items = [UserInventoryItem(user_profile=winner_profile, skin_id=skin_pk) for skin_pk in all_unboxed_skins_pks]
                    UserInventoryItem.objects.bulk_create(new_items)
                    print(f"Savaş #{battle.id}: {len(new_items)} skin '{winner_profile.user.username}' verildi.")
                    if consolation_skin:
                        loser_items = [UserInventoryItem(user_profile=loser.user_profile, skin=consolation_skin) for loser in losers]
                        UserInventoryItem.objects.bulk_create(loser_items)
                        print(f"Savaş #{battle.id}: {len(losers)} kaybedene teselli verildi: {consolation_skin.name}")
                else: print(f"Savaş #{battle.id}: Beraberlik! Ödül dağıtımı yok.")
            elif battle.mode == CaseBattle.BattleMode.SHARED:
                num_real_winners = len(winners)
                if num_real_winners > 0:
                    value_per_winner = (battle.total_value / decimal.Decimal(num_real_winners)).quantize(decimal.Decimal("0.01"), rounding=decimal.ROUND_DOWN)
                    print(f"Savaş #{battle.id}: Ortak mod. Kişi başı bakiye: {value_per_winner}")
                    profiles_to_update_pks = [w.user_profile.pk for w in winners]
                    # F() objesi ile atomik güncelleme
                    UserProfile.objects.filter(pk__in=profiles_to_update_pks).update(balance=F('balance') + value_per_winner)
                    print(f"Savaş #{battle.id}: Ortak mod bakiyeleri güncellendi.")
                    # !!! messages.info(request, ...) BURADAN KALDIRILDI !!!

        # 5. Durumu 'FINISHED' yap
        battle.status = CaseBattle.BattleStatus.FINISHED
        battle.finished_at = timezone.now()
        battle.save(update_fields=['status', 'finished_at', 'total_value'])
        print(f"!!! Savaş #{battle.id} başarıyla tamamlandı.")

    except Exception as e_run:
        print(f"HATA: Savaş #{battle.id} yürütülürken hata oluştu! {e_run}")
        battle.status = CaseBattle.BattleStatus.ERROR
        battle.finished_at = timezone.now(); battle.save(update_fields=['status', 'finished_at'])
# --- --- --- --- --- --- --- --- --- --- --- ---

# --- Bot Ekleme AJAX (Güncellenmiş) ---
@login_required
@transaction.atomic
def add_bot_to_battle_ajax(request, battle_id):
    # ... (önceki gibi, start_battle_logic çağrısı dahil) ...
    if request.method != 'POST': return JsonResponse({'success': False, 'error': 'Sadece POST.'})
    battle = get_object_or_404(CaseBattle, pk=battle_id)
    try: user_profile = request.user.profile
    except UserProfile.DoesNotExist: return JsonResponse({'success': False, 'error': 'Profil bulunamadı.'})
    if battle.creator != user_profile: return JsonResponse({'success': False, 'error': 'Sadece kurucu bot ekleyebilir.'})
    if not battle.is_joinable(): return JsonResponse({'success': False, 'error': 'Savaş dolu veya katılım beklenmiyor.'})

    final_battle_status = battle.status
    is_full_now = False

    try:
        CaseBattleParticipant.objects.create(battle=battle, user_profile=None, is_bot=True)
        current_participants = battle.get_participant_count()
        is_full_now = current_participants == battle.max_participants
        battle_status_for_response = battle.status
        if is_full_now:
            try:
                start_battle_logic(battle) # Savaş başlat ve bitir
                battle_status_for_response = battle.status # Biten durumu al
            except Exception as e_start:
                print(f"HATA: Savaş #{battle.id} başlatılamadı! {e_start}")
                battle_status_for_response = CaseBattle.BattleStatus.ERROR

        return JsonResponse({'success': True, 'message': 'Bot eklendi.' if not is_full_now else 'Son bot eklendi, savaş tamamlandı!', 'participant_count': current_participants, 'is_full': is_full_now, 'battle_status': battle_status_for_response })
    except Exception as e: print(f"Bot ekleme hatası: {e}"); return JsonResponse({'success': False, 'error': 'Bot eklenirken hata oluştu.'})

# --- Savaş Sonuçlarını Getirme AJAX (Güncellenmiş - prefetch eklendi) ---
@login_required
def get_battle_results_ajax(request, battle_id):
    battle = get_object_or_404(CaseBattle.objects.prefetch_related('participants__user_profile__user', 'participants__unboxings__unboxed_skin__rarity'), pk=battle_id) # Prefetch eklendi
    if battle.status != CaseBattle.BattleStatus.FINISHED: return JsonResponse({'success': False, 'error': 'Savaş henüz bitmedi.'})
    participants_data = []
    for p in battle.participants.all():
        unboxings = [{'id': ub.unboxed_skin.id, 'name': ub.unboxed_skin.name, 'image_url': ub.unboxed_skin.image_url or '', 'rarity_color': ub.unboxed_skin.rarity.color_hex if ub.unboxed_skin.rarity else '#FFFFFF', 'value': ub.unboxed_skin.value} for ub in p.unboxings.all()]
        participants_data.append({'id': p.id, 'name': p.get_display_name(), 'is_bot': p.is_bot, 'total_value': p.total_unboxed_value, 'is_winner': p.is_winner, 'unboxings': unboxings})
    return JsonResponse({ 'success': True, 'participants': participants_data })



# --- YENİ AJAX View: Savaşı Sonlandırma ve Ödül Dağıtma ---
@login_required
@transaction.atomic
def finalize_battle_ajax(request, battle_id):
    if request.method != 'POST': return JsonResponse({'success': False, 'error': 'Sadece POST.'})
    battle = get_object_or_404(CaseBattle.objects.prefetch_related('participants__user_profile', 'participants__unboxings__unboxed_skin'), pk=battle_id)

    # Sadece 'STARTING' durumundaki savaş sonlandırılabilir
    if battle.status != CaseBattle.BattleStatus.STARTING:
        return JsonResponse({'success': False, 'error': 'Savaş zaten bitmiş veya başlamamış.'})

    print(f"--- Savaş #{battle.id} Sonlandırılıyor (FINISHING)... ---")
    try:
        winners = list(battle.participants.filter(is_winner=True).select_related('user_profile')) # Kazananları tekrar al
        losers = list(battle.participants.filter(is_winner=False, is_bot=False).select_related('user_profile')) # Gerçek kaybedenler
        real_participants = [p for p in winners if not p.is_bot] # Gerçek kazananlar/pay alacaklar

        # 1. Ödülleri Dağıt
        consolation_skin = None
        if losers and (battle.mode == CaseBattle.BattleMode.STANDARD or battle.mode == CaseBattle.BattleMode.UNDERDOG):
             consolation_skin = Skin.objects.filter(value__gt=0, value__lt=5).order_by('?').first()

        if winners:
            if battle.mode == CaseBattle.BattleMode.STANDARD or battle.mode == CaseBattle.BattleMode.UNDERDOG:
                if len(winners) == 1 and not winners[0].is_bot: # Tek gerçek kazanan varsa
                    winner_profile = winners[0].user_profile
                    skins_to_give_pks = CaseBattleUnboxing.objects.filter(battle_participant__battle=battle).values_list('unboxed_skin_id', flat=True)
                    new_items = [UserInventoryItem(user_profile=winner_profile, skin_id=skin_pk) for skin_pk in skins_to_give_pks]
                    UserInventoryItem.objects.bulk_create(new_items)
                    print(f"Savaş #{battle.id}: {len(new_items)} skin '{winner_profile.user.username}' verildi.")
                    if consolation_skin: # Kaybedenlere teselli
                        loser_items = [UserInventoryItem(user_profile=loser.user_profile, skin=consolation_skin) for loser in losers]
                        UserInventoryItem.objects.bulk_create(loser_items)
                        print(f"Savaş #{battle.id}: {len(losers)} kaybedene teselli verildi: {consolation_skin.name}")
                elif len(winners) > 1: print(f"Savaş #{battle.id}: Beraberlik! Ödül dağıtımı yok.")
                elif len(winners) == 1 and winners[0].is_bot: print(f"Savaş #{battle.id}: Bot kazandı! Ödül dağıtımı yok.") # Bot kazanırsa
                else: print(f"Savaş #{battle.id}: Kazanan durumu belirsiz, ödül dağıtımı yok.")

            elif battle.mode == CaseBattle.BattleMode.SHARED:
                num_real_participants = len(real_participants) # real_participants zaten 'winners' listesi
                if num_real_participants > 0:
                    value_per_winner = (battle.total_value / decimal.Decimal(num_real_participants)).quantize(decimal.Decimal("0.01"), rounding=decimal.ROUND_DOWN)
                    profiles_to_update_pks = [w.user_profile.pk for w in real_participants]
                    UserProfile.objects.filter(pk__in=profiles_to_update_pks).update(balance=F('balance') + value_per_winner)
                    messages.success(request, f"Ortak Savaş #{battle.id} sonucu {value_per_winner}₺ bakiyenize eklendi.") # Mesajı burada oluştur
                    print(f"Savaş #{battle.id}: Ortak mod bakiyeleri güncellendi ({value_per_winner}₺ per user).")

        # 2. Durumu 'FINISHED' yap
        battle.status = CaseBattle.BattleStatus.FINISHED
        battle.finished_at = timezone.now()
        battle.save(update_fields=['status', 'finished_at']) # Sadece bu alanları güncelle
        print(f"!!! Savaş #{battle.id} başarıyla SONLANDIRILDI (FINISHED).")
        return JsonResponse({'success': True, 'message': 'Savaş başarıyla sonlandırıldı.'})

    except Exception as e_finalize:
        print(f"HATA: Savaş #{battle.id} sonlandırılırken hata oluştu! {e_finalize}")
        battle.status = CaseBattle.BattleStatus.ERROR
        battle.finished_at = timezone.now()
        battle.save(update_fields=['status', 'finished_at'])
        return JsonResponse({'success': False, 'error': 'Savaş sonlandırılırken hata oluştu.'})