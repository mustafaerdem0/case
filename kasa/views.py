# --- File: kasa/views.py (Yeniden Formatlanmış - Alt Alta) ---

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseBadRequest
from django.db import transaction, models
from django.urls import reverse
from django.db.models import Sum, Q, Min, Max, F
from django.contrib import messages
from django.utils import timezone
from django.templatetags.static import static
import json
from django.core.serializers.json import DjangoJSONEncoder

from .models import (Case, Skin, UserProfile, CaseSkin, UserInventoryItem, UpgradeAttempt,
                     CaseBattle, CaseBattleParticipant, CaseBattleUnboxing, Rarity)
from .forms import CreateCaseBattleForm

import random
import decimal

# === Temel View'lar ===

def home(request):
    active_cases = Case.objects.filter(is_active=True)
    context = {'cases': active_cases}
    return render(request, 'kasalar.html', context)

def case_detail(request, case_id):
    case = get_object_or_404(Case, pk=case_id, is_active=True)
    possible_skins = CaseSkin.objects.filter(case=case).select_related('skin', 'skin__rarity').order_by('-probability')
    ajax_open_url = reverse('open_case_ajax', args=[case.id])
    context = {
        'case': case,
        'possible_skins': possible_skins,
        'ajax_open_url': ajax_open_url
    }
    return render(request, 'kasa-ac.html', context)

@login_required
def profile(request):
    try:
        user_profile = request.user.profile
    except UserProfile.DoesNotExist:
        messages.error(request,"Profil bulunamadı.")
        return redirect('home')

    inventory_items = UserInventoryItem.objects.filter(
        user_profile=user_profile,
        status=UserInventoryItem.ItemStatus.AVAILABLE
    ).select_related('skin', 'skin__rarity')
    trade_url_update_url = reverse('update_trade_url_ajax')
    context = {
        'profile': user_profile,
        'inventory': inventory_items,
        'trade_url_update_url': trade_url_update_url
    }
    return render(request, 'kazanilan_skinler.html', context)

@login_required
def deposit_page(request):
    return render(request, 'bakiye_ekle.html', {})

@login_required
def withdraw_page(request):
    return redirect('profile')

@login_required
def upgrade_page(request):
    user_profile = get_object_or_404(UserProfile, user=request.user)
    user_inventory = UserInventoryItem.objects.filter(
        user_profile=user_profile, status=UserInventoryItem.ItemStatus.AVAILABLE
    ).select_related('skin', 'skin__rarity').order_by('-skin__value')
    owned_skin_ids = user_inventory.values_list('skin_id', flat=True)
    potential_targets = Skin.objects.filter(
        value__gt=0
    ).exclude(id__in=owned_skin_ids).select_related('rarity').order_by('value')
    calculate_url = reverse('calculate_upgrade_ajax')
    perform_url = reverse('perform_upgrade_ajax')
    context = {
        'inventory': user_inventory,
        'potential_targets': potential_targets,
        'calculate_url': calculate_url,
        'perform_url': perform_url,
        'profile': user_profile
    }
    return render(request, 'upgrade.html', context)

# === AJAX View'ları ===

@login_required
@transaction.atomic
def open_case_ajax(request, case_id):
    if request.method != 'POST':
        return HttpResponseBadRequest("Sadece POST.")

    case = get_object_or_404(Case, pk=case_id, is_active=True)
    user_profile = get_object_or_404(UserProfile, user=request.user)
    case_price = decimal.Decimal(case.price)

    if user_profile.balance < case_price:
        return JsonResponse({'success': False, 'error': 'Yetersiz bakiye!'})

    case_skins_data = CaseSkin.objects.filter(case=case).select_related('skin','skin__rarity')
    if not case_skins_data.exists():
        return JsonResponse({'success': False, 'error': 'Kasada eşya yok!'})

    skins = [cs.skin for cs in case_skins_data]
    probabilities = [max(0, cs.probability) for cs in case_skins_data] # Negatif olasılıkları engelle
    total_prob = sum(probabilities)

    if total_prob <= 0 and not skins: # Olasılık yoksa ve skin yoksa
         return JsonResponse({'success': False, 'error': 'Kasada geçerli eşya veya olasılık yok!'})
    elif total_prob <= 0 and skins: # Olasılık yok ama skin varsa rastgele seç
        print(f"Uyarı: Kasa ID {case.id} için olasılıklar toplamı 0 veya negatif. Rastgele seçiliyor.")
        won_skin = random.choice(skins)
    elif not (0.95 < total_prob < 1.05): # Toleranslı olasılık kontrolü
        print(f"Uyarı: Kasa ID {case.id} prob toplamı ({total_prob}) 1'den farklı!")
        # İsteğe bağlı: Olasılıkları normalize edebiliriz veya hatayı kabul edebiliriz
        # weights = [p / total_prob for p in probabilities] if total_prob > 0 else None
        # won_skin = random.choices(skins, weights=weights, k=1)[0] if weights else random.choice(skins)
        try:
            won_skin = random.choices(skins, weights=probabilities, k=1)[0]
        except (IndexError, ValueError) as e:
             print(f"Hata: random.choices - {e}. Kasa ID: {case.id}")
             won_skin = random.choice(skins) if skins else None # Fallback
    else: # Olasılıklar normal
        try:
            won_skin = random.choices(skins, weights=probabilities, k=1)[0]
        except (IndexError, ValueError) as e:
             print(f"Hata: random.choices (normal) - {e}. Kasa ID: {case.id}")
             won_skin = None

    if not won_skin:
        return JsonResponse({'success': False, 'error': 'Skin seçimi sırasında hata oluştu.'})

    # Bakiye düşürme ve envantere ekleme
    user_profile.balance -= case_price
    user_profile.save(update_fields=['balance'])
    UserInventoryItem.objects.create(
        user_profile=user_profile,
        skin=won_skin,
        status=UserInventoryItem.ItemStatus.AVAILABLE
    )

    # Reel datası oluşturma
    reel_length = 50
    reel_items_data = []
    possible_reel_skins = list(case_skins_data)
    placeholder_img = static('img/placeholder.png') # Placeholder'ı bir kere alalım
    for _ in range(reel_length - 1):
        chosen_cs = random.choice(possible_reel_skins)
        rarity = chosen_cs.skin.rarity
        reel_items_data.append({
            'id': chosen_cs.skin.id,
            'name': chosen_cs.skin.name,
            'image_url': chosen_cs.skin.image_url or placeholder_img, # Direkt field veya placeholder
            'rarity_color': rarity.color_hex if rarity else '#FFFFFF',
            'rarity_name': rarity.name if rarity else 'N/A'
        })

    winner_index = 40
    won_skin_rarity = won_skin.rarity
    reel_items_data.insert(winner_index, {
        'id': won_skin.id,
        'name': won_skin.name,
        'image_url': won_skin.image_url or placeholder_img, # Direkt field veya placeholder
        'rarity_color': won_skin_rarity.color_hex if won_skin_rarity else '#FFFFFF',
        'rarity_name': won_skin_rarity.name if won_skin_rarity else 'N/A'
    })

    return JsonResponse({
        'success': True,
        'reel_items': reel_items_data,
        'winner_index': winner_index,
        'won_skin': {
            'name': won_skin.name,
            'image_url': won_skin.image_url or placeholder_img,
            'rarity_name': won_skin_rarity.name if won_skin_rarity else 'N/A',
            'rarity_color': won_skin_rarity.color_hex if won_skin_rarity else '#FFFFFF'
        },
        'new_balance': user_profile.balance
    })


@login_required
def update_trade_url_ajax(request):
    if request.method != 'POST':
        return HttpResponseBadRequest("Sadece POST.")
    new_trade_url = request.POST.get('trade_url', '').strip()
    if not new_trade_url or not new_trade_url.startswith('https://steamcommunity.com/tradeoffer/new/'):
        return JsonResponse({'success': False, 'error': 'Geçersiz URL.'})
    try:
        profile = request.user.profile
        profile.trade_url = new_trade_url
        profile.save(update_fields=['trade_url'])
        return JsonResponse({'success': True, 'message': 'URL güncellendi.'})
    except UserProfile.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Profil bulunamadı.'})
    except Exception as e:
        print(f"Trade URL error: {e}")
        return JsonResponse({'success': False, 'error': 'Güncellenemedi.'})


def calculate_upgrade_chance(input_val, target_val):
    if target_val <= 0 or input_val <= 0:
        return 0.0
    # Değerleri Decimal olarak tutalım
    input_d = decimal.Decimal(input_val)
    target_d = decimal.Decimal(target_val)
    if target_d == 0: return 0.0 # Sıfıra bölme hatası önlemi
    ratio = float(input_d / target_d)
    multiplier = 0.85
    chance = ratio * multiplier
    return max(0.01, min(chance, 0.90))


@login_required
def calculate_upgrade_ajax(request):
    if request.method != 'POST':
        return HttpResponseBadRequest("Sadece POST.")
    try:
        data = json.loads(request.body)
        input_ids = data.get('input_item_ids', [])
        target_id = data.get('target_skin_id')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Geçersiz istek.'})

    if not input_ids or not target_id:
        return JsonResponse({'success': False, 'error': 'Girdi/hedef seçilmedi.'})

    try:
        profile = request.user.profile
        items = UserInventoryItem.objects.filter(
            user_profile=profile,
            id__in=input_ids,
            status=UserInventoryItem.ItemStatus.AVAILABLE
        ).select_related('skin')
    except UserProfile.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Profil bulunamadı.'})

    # Seçilen item sayısı ile bulunan item sayısını karşılaştır
    if len(input_ids) != items.count():
        return JsonResponse({'success': False, 'error': 'Eşyalar geçersiz veya kullanılamaz.'})

    input_val = items.aggregate(total=Sum('skin__value'))['total'] or decimal.Decimal('0.00')

    try:
        target = Skin.objects.get(pk=target_id)
    except Skin.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Hedef bulunamadı.'})

    chance = calculate_upgrade_chance(input_val, target.value)
    return JsonResponse({
        'success': True,
        'chance': round(chance * 100, 2),
        'total_input_value': input_val,
        'target_skin_value': target.value
    })

@login_required
@transaction.atomic
def perform_upgrade_ajax(request):
    if request.method != 'POST':
        return HttpResponseBadRequest("Sadece POST.")
    try:
        data = json.loads(request.body)
        input_ids = data.get('input_item_ids', [])
        target_id = data.get('target_skin_id')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Geçersiz istek.'})

    if not input_ids or not target_id:
        return JsonResponse({'success': False, 'error': 'Girdi/hedef seçilmedi.'})

    try:
        profile = request.user.profile
        target = Skin.objects.get(pk=target_id)
    except (UserProfile.DoesNotExist, Skin.DoesNotExist):
        return JsonResponse({'success': False, 'error': 'Profil/hedef bulunamadı.'})

    items = UserInventoryItem.objects.select_for_update().filter(
        user_profile=profile,
        id__in=input_ids,
        status=UserInventoryItem.ItemStatus.AVAILABLE
    ).select_related('skin', 'skin__rarity')

    if len(input_ids) != items.count() or not items.exists():
        return JsonResponse({'success': False, 'error': 'Eşyalar geçersiz/kullanımda.'})

    input_val = items.aggregate(total=Sum('skin__value'))['total'] or decimal.Decimal('0.00')
    chance = calculate_upgrade_chance(input_val, target.value)
    rolled = random.random()
    success = rolled < chance

    try:
        updated_count = items.update(status=UserInventoryItem.ItemStatus.USED_UPGRADE)
        if updated_count != len(input_ids):
             raise Exception("Yükseltme sırasında eşya durumu güncellenemedi.")
    except Exception as e:
        print(f"Upgrade item status update failed: {e}")
        return JsonResponse({'success': False, 'error': 'Yükseltme sırasında beklenmedik bir hata oluştu.'})

    # Denemeyi kaydet
    UpgradeAttempt.objects.create(
        user_profile=profile, input_value=input_val, target_skin=target,
        target_value=target.value, success_chance=chance, rolled_number=rolled,
        was_successful=success
    )

    outcome_str = 'successful' if success else 'failed'
    response_data = {
        'success': True,
        'outcome': outcome_str,
        'message': '',
        'chance': round(chance * 100, 2),
        'rolled': round(rolled * 100, 2)
    }

    if success:
        UserInventoryItem.objects.create(
            user_profile=profile, skin=target, status=UserInventoryItem.ItemStatus.AVAILABLE
        )
        response_data['message'] = f'Tebrikler! {target.name} kazandınız!'
        target_rarity = target.rarity
        response_data['won_skin'] = {
            'name': target.name,
            'image_url': target.image_url or '',
            'rarity_name': target_rarity.name if target_rarity else 'N/A',
            'rarity_color': target_rarity.color_hex if target_rarity else '#FFFFFF'
        }
    else:
        response_data['message'] = 'Yükseltme başarısız.'

    return JsonResponse(response_data)


# === Kasa Savaşları View'ları ===

@login_required
def active_battles_list(request):
    battles = CaseBattle.objects.filter(
        status=CaseBattle.BattleStatus.WAITING
    ).select_related('creator__user').prefetch_related(
        'participants__user_profile__user', 'cases'
    ).order_by('-created_at')
    context = {'battles': battles}
    return render(request, 'active_battles.html', context)

@login_required
@transaction.atomic
def create_battle(request):
    if request.method == 'POST':
        form = CreateCaseBattleForm(request.POST)
        if form.is_valid():
            try:
                user_profile = request.user.profile
            except UserProfile.DoesNotExist:
                 messages.error(request,"Profil bulunamadı.")
                 context = {'form': form}
                 return render(request, 'create_battle.html', context)

            selected_cases = form.cleaned_data['cases']
            mode = form.cleaned_data['mode']
            max_participants = int(form.cleaned_data['max_participants'])
            total_cost = sum(case.price for case in selected_cases)

            # Bakiye kontrolü
            # Note: concurrent requests might still cause issues, use select_for_update if needed
            if user_profile.balance < total_cost:
                messages.error(request, f"Yetersiz bakiye! Gerekli: {total_cost}₺")
                context = {'form': form}
                return render(request, 'create_battle.html', context)
            else:
                try:
                    user_profile.balance = F('balance') - total_cost
                    user_profile.save(update_fields=['balance'])
                    # Refresh to get the actual balance if needed elsewhere
                    # user_profile.refresh_from_db()

                    new_battle = CaseBattle.objects.create(
                        creator=user_profile,
                        mode=mode,
                        max_participants=max_participants
                    )
                    new_battle.cases.set(selected_cases)

                    CaseBattleParticipant.objects.create(
                        battle=new_battle,
                        user_profile=user_profile,
                        is_bot=False
                    )
                    messages.success(request, "Savaş başarıyla oluşturuldu!")
                    return redirect('battle_detail', battle_id=new_battle.id)
                except Exception as e:
                     # Transaction ensures balance deduction is rolled back on error
                     print(f"Savaş oluşturma DB hatası: {e}")
                     messages.error(request, "Savaş oluşturulurken veritabanı hatası oluştu.")
                     context = {'form': form}
                     return render(request, 'create_battle.html', context)
        else: # Form geçerli değilse
             messages.error(request, "Lütfen formdaki hataları düzeltin.")
             context = {'form': form}
             return render(request, 'create_battle.html', context)
    else: # GET request
        form = CreateCaseBattleForm()
        context = {'form': form}
        return render(request, 'create_battle.html', context)

@login_required
def battle_detail(request, battle_id):
     battle = get_object_or_404(
         CaseBattle.objects.select_related('creator__user').prefetch_related(
             'participants__user_profile__user',
             'cases__skins__rarity',
             'participants__unboxings__unboxed_skin__rarity'
         ),
         pk=battle_id
     )

     is_creator = False
     is_participant = False
     user_profile = None
     can_start_battle = False
     value_per_participant = None
     col_lg_class_value = 6
     possible_skins_json = '[]'

     if hasattr(request.user, 'profile'):
        try:
            user_profile = request.user.profile
            is_creator = battle.creator == user_profile if battle.creator else False
            is_participant = battle.participants.filter(user_profile=user_profile).exists()
        except UserProfile.DoesNotExist:
            pass # Kullanıcının profili olmayabilir

     participant_count = battle.get_participant_count()
     is_full = participant_count == battle.max_participants

     can_join = battle.status == CaseBattle.BattleStatus.WAITING and not is_full and not is_participant
     can_add_bot = is_creator and battle.status == CaseBattle.BattleStatus.WAITING and not is_full
     # Savaş başlatma koşulu
     if is_creator and battle.status == CaseBattle.BattleStatus.WAITING and is_full:
         can_start_battle = True

     winners = battle.participants.filter(is_winner=True)
     multiple_winners = winners.count() > 1

     # Ortak mod değeri
     if battle.status == CaseBattle.BattleStatus.FINISHED and battle.mode == CaseBattle.BattleMode.SHARED:
        real_participant_count = battle.get_real_participant_count()
        if real_participant_count > 0:
            try:
                value_per_participant = (battle.total_value / decimal.Decimal(real_participant_count)).quantize(decimal.Decimal("0.01"), rounding=decimal.ROUND_DOWN)
            except decimal.InvalidOperation:
                 value_per_participant = decimal.Decimal('0.00')

     # Sütun genişliği
     if participant_count == 3:
         col_lg_class_value = 4
     elif participant_count >= 4:
         col_lg_class_value = 3
     elif participant_count == 1:
         col_lg_class_value = 12

     # Animasyon için olası skinler
     try:
         possible_skins_in_battle = []
         seen_skin_ids = set()
         placeholder_url = static('img/placeholder.png')
         for case in battle.cases.all():
             for skin in case.skins.all():
                  if skin.id not in seen_skin_ids:
                      rarity = skin.rarity
                      possible_skins_in_battle.append({
                          'id': skin.id,
                          'name': skin.name,
                          'image_url': skin.image_url or placeholder_url,
                          'rarity_color': rarity.color_hex if rarity else '#FFFFFF',
                          'rarity_name': rarity.name if rarity else 'common',
                          'value': skin.value
                      })
                      seen_skin_ids.add(skin.id)
         possible_skins_json = json.dumps(possible_skins_in_battle, cls=DjangoJSONEncoder)
     except Exception as e:
         print(f"Hata: possible_skins_json oluşturulamadı - {e}")
         possible_skins_json = '[]' # Hata durumunda boş liste

     context = {
         'battle': battle,
         'is_creator': is_creator,
         'is_participant': is_participant,
         'can_join': can_join,
         'can_add_bot': can_add_bot,
         'can_start_battle': can_start_battle,
         'winners': winners,
         'multiple_winners': multiple_winners,
         'value_per_participant': value_per_participant,
         'col_lg_class_value': col_lg_class_value,
         'possible_skins_json': possible_skins_json,
     }
     return render(request, 'battle_detail.html', context)


# --- Yardımcı Kasa Açma Fonksiyonu ---
def _perform_single_unboxing(case: Case) -> Skin | None:
    case_skins_data = CaseSkin.objects.filter(case=case).select_related('skin', 'skin__rarity')
    if not case_skins_data.exists():
        return None
    skins = [cs.skin for cs in case_skins_data]
    probabilities = [max(0, cs.probability) for cs in case_skins_data]
    total_prob = sum(probabilities)
    if total_prob <= 0:
        print(f"Uyarı: Kasa ID {case.id} için geçerli olasılık yok veya skin yok.")
        return random.choice(skins) if skins else None
    if not (0.95 < total_prob < 1.05):
        print(f"Uyarı: Kasa ID {case.id} prob toplamı ({total_prob}) 1'den çok farklı!")
    try:
        return random.choices(skins, weights=probabilities, k=1)[0]
    except (IndexError, ValueError) as e:
        print(f"Hata: _perform_unboxing - {e}. Kasa ID: {case.id}")
        # Hata durumunda rastgele bir skin döndürmek yerine None döndürmek daha iyi olabilir
        return None

# --- SAVAŞ MANTIĞINI ÇALIŞTIRAN ANA FONKSİYON ---
@transaction.atomic
def run_and_finalize_battle(battle: CaseBattle):
    print(f"!!! Savaş #{battle.id} Mantığı Çalıştırılıyor... (Mod: {battle.mode})")
    if battle.status != CaseBattle.BattleStatus.WAITING:
        print(f"Uyarı: Savaş #{battle.id} zaten başlatılmış/bitmiş.")
        return None
    battle.status = CaseBattle.BattleStatus.STARTING
    battle.started_at = timezone.now()
    battle.save(update_fields=['status', 'started_at'])

    unboxing_results_for_js = {} # {participant_id: [skin_dict, ...]}
    try:
        participant_totals = {}
        participants = list(battle.participants.select_related('user_profile__user').all())
        unboxings_to_create = []
        all_unboxed_skins_pks = []

        # 1. Kasaları Aç
        for participant in participants:
            participant_total = decimal.Decimal('0.00')
            participant_unboxings = []
            for case in battle.cases.all():
                won_skin = _perform_single_unboxing(case)
                if won_skin:
                    unboxings_to_create.append(
                        CaseBattleUnboxing(battle_participant=participant, case=case, unboxed_skin=won_skin)
                    )
                    participant_total += won_skin.value
                    all_unboxed_skins_pks.append(won_skin.pk)
                    rarity = won_skin.rarity
                    participant_unboxings.append({
                        'id': won_skin.id, 'name': won_skin.name,
                        'image_url': won_skin.image_url or '',
                        'rarity_color': rarity.color_hex if rarity else '#FFFFFF',
                        'value': float(won_skin.value), # JSON için float'a çevir
                        'rarity_name': rarity.name if rarity else 'common'
                    })
                else:
                    print(f"Uyarı: Savaş #{battle.id}, P:{participant.id}, C:{case.name} açılamadı.")
            participant.total_unboxed_value = participant_total
            unboxing_results_for_js[str(participant.id)] = participant_unboxings # JS için sakla
            if not participant.is_bot and participant.user_profile:
                participant_totals[participant.id] = participant_total

        if unboxings_to_create:
            CaseBattleUnboxing.objects.bulk_create(unboxings_to_create)

        # 2. Toplam Değer
        battle.total_value = sum(p.total_unboxed_value for p in participants)

        # 3. Kazananı Belirle
        winners = []
        losers = []
        real_participants = [p for p in participants if not p.is_bot and p.user_profile]

        if real_participants:
            valid_totals = {p.id: p.total_unboxed_value for p in real_participants}
            valid_totals_for_min_max = {pid: val for pid, val in valid_totals.items() if val > 0}

            if battle.mode == CaseBattle.BattleMode.STANDARD:
                 if valid_totals_for_min_max:
                     max_value = max(valid_totals_for_min_max.values())
                     winners_ids = {pid for pid, val in valid_totals.items() if val == max_value}
                     winners = [p for p in real_participants if p.id in winners_ids]
                 elif valid_totals: # Hepsi 0 ise
                     winners = real_participants # Beraberlik
            elif battle.mode == CaseBattle.BattleMode.UNDERDOG:
                 if valid_totals_for_min_max:
                     min_value = min(valid_totals_for_min_max.values())
                     winners_ids = {pid for pid, val in valid_totals.items() if val == min_value}
                     winners = [p for p in real_participants if p.id in winners_ids]
                 elif valid_totals: # Hepsi 0 ise
                     winners = real_participants # Beraberlik
            elif battle.mode == CaseBattle.BattleMode.SHARED:
                 winners = real_participants # Shared'de hepsi pay alır

            losers = [p for p in real_participants if p not in winners]

        # Kazananları ve değerleri topluca güncelle
        for p in participants:
            p.is_winner = (p in winners)
        CaseBattleParticipant.objects.bulk_update(participants, ['total_unboxed_value', 'is_winner'])

        # 4. Ödülleri Dağıt
        consolation_skin = None
        loser_items = [] # <<< Başlatma
        if losers and (battle.mode == CaseBattle.BattleMode.STANDARD or battle.mode == CaseBattle.BattleMode.UNDERDOG):
             consolation_skin = Skin.objects.filter(value__gt=0, value__lt=5).order_by('?').first()

        if winners:
            if battle.mode == CaseBattle.BattleMode.STANDARD or battle.mode == CaseBattle.BattleMode.UNDERDOG:
                if len(winners) == 1 and not winners[0].is_bot:
                    winner_profile = winners[0].user_profile
                    new_items = [UserInventoryItem(user_profile=winner_profile, skin_id=skin_pk) for skin_pk in all_unboxed_skins_pks]
                    if new_items:
                        UserInventoryItem.objects.bulk_create(new_items)
                        print(f"Savaş #{battle.id}: {len(new_items)} skin '{winner_profile.user.username}' verildi.")
                elif len(winners) > 1:
                    print(f"Savaş #{battle.id}: Beraberlik! ({len(winners)} kazanan). Ödül dağıtımı yok.")
                elif len(winners) == 1 and winners[0].is_bot:
                    print(f"Savaş #{battle.id}: Bot kazandı! Ödül dağıtımı yok.")

                # Teselli ödülü (kazanan 1 kişi olsa bile verilebilir)
                if consolation_skin and losers:
                    loser_items = [UserInventoryItem(user_profile=loser.user_profile, skin=consolation_skin) for loser in losers if loser.user_profile]
                    if loser_items:
                        UserInventoryItem.objects.bulk_create(loser_items)
                        print(f"Savaş #{battle.id}: {len(losers)} kaybedene teselli verildi: {consolation_skin.name}")

            elif battle.mode == CaseBattle.BattleMode.SHARED:
                num_real_winners = len(winners) # winners = real_participants
                if num_real_winners > 0:
                    value_per_winner = (battle.total_value / decimal.Decimal(num_real_winners)).quantize(decimal.Decimal("0.01"), rounding=decimal.ROUND_DOWN)
                    print(f"Savaş #{battle.id}: Ortak mod. Kişi başı bakiye: {value_per_winner}")
                    profiles_to_update_pks = [w.user_profile.pk for w in winners if w.user_profile]
                    if profiles_to_update_pks:
                         # ---- AYRI SATIR ----
                         UserProfile.objects.filter(pk__in=profiles_to_update_pks).update(balance=F('balance') + value_per_winner)
                         print(f"Savaş #{battle.id}: Ortak mod bakiyeleri güncellendi.")
                    # ---- ----

        # 5. Durumu 'FINISHED' yap
        battle.status = CaseBattle.BattleStatus.FINISHED
        battle.finished_at = timezone.now()
        battle.save(update_fields=['status', 'finished_at', 'total_value'])
        print(f"!!! Savaş #{battle.id} başarıyla tamamlandı.")
        return unboxing_results_for_js # Başarılı olursa sonuçları döndür

    except Exception as e_run:
        print(f"HATA: Savaş #{battle.id} yürütülürken hata oluştu! {e_run}")
        battle.status = CaseBattle.BattleStatus.ERROR
        battle.finished_at = timezone.now()
        battle.save(update_fields=['status', 'finished_at'])
        return None # Hata durumunda None döndür
# --- --- --- --- --- --- --- --- --- --- --- ---

# --- Bot Ekleme AJAX ---
@login_required
@transaction.atomic
def add_bot_to_battle_ajax(request, battle_id):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Sadece POST.'})
    battle = get_object_or_404(CaseBattle, pk=battle_id)
    try:
         user_profile = request.user.profile
    except UserProfile.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Profil bulunamadı.'})
    if battle.creator != user_profile:
        return JsonResponse({'success': False, 'error': 'Sadece kurucu bot ekleyebilir.'})
    if not battle.is_joinable():
        return JsonResponse({'success': False, 'error': 'Savaş dolu veya katılım beklenmiyor.'})

    is_full_now = False
    try:
        CaseBattleParticipant.objects.create(battle=battle, user_profile=None, is_bot=True)
        current_participants = battle.get_participant_count()
        is_full_now = current_participants == battle.max_participants
        # Savaşa başlatma yok
        return JsonResponse({
            'success': True,
            'message': 'Bot eklendi.' + (' Savaş şimdi başlatılabilir!' if is_full_now else ''),
            'participant_count': current_participants,
            'is_full': is_full_now
            # Status veya unboxing data yok
        })
    except Exception as e:
        print(f"Bot ekleme hatası: {e}") # Ayrı satır
        return JsonResponse({'success': False, 'error': 'Bot eklenirken bir hata oluştu.'})


# --- Savaşı Başlatma AJAX ---
@login_required
@transaction.atomic
def start_battle_ajax(request, battle_id):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Sadece POST.'})
    battle = get_object_or_404(CaseBattle, pk=battle_id)
    try:
        user_profile = request.user.profile
    except UserProfile.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Profil bulunamadı.'})
    if battle.creator != user_profile:
        return JsonResponse({'success': False, 'error': 'Sadece kurucu savaşı başlatabilir.'})
    if battle.status != CaseBattle.BattleStatus.WAITING:
        return JsonResponse({'success': False, 'error': 'Savaş zaten başlamış veya bitmiş.'})
    if battle.get_participant_count() != battle.max_participants:
        return JsonResponse({'success': False, 'error': 'Savaş henüz tam olarak dolmadı.'})

    unboxing_results = None # Başlat
    final_battle_status = CaseBattle.BattleStatus.ERROR # Varsayılan hata
    try:
        # <<< run_and_finalize_battle çağırılıyor >>>
        unboxing_results = run_and_finalize_battle(battle)
        # refresh_from_db son durumu almak için önemli
        battle.refresh_from_db()
        final_battle_status = battle.status

        if final_battle_status == CaseBattle.BattleStatus.FINISHED and unboxing_results is not None:
             response_data = {
                 'success': True,
                 'message': 'Savaş başlatıldı ve tamamlandı!',
                 'battle_status': final_battle_status,
                 'unboxing_results': unboxing_results
                }
             return JsonResponse(response_data)
        else:
             error_message = 'Savaş yürütülürken bir hata oluştu.' if final_battle_status == CaseBattle.BattleStatus.ERROR else 'Sonuçlar alınamadı veya savaş bitmedi.'
             return JsonResponse({'success': False, 'error': error_message, 'battle_status': final_battle_status })
    except Exception as e_run:
         # Bu except bloğu normalde run_and_finalize_battle içindeki except tarafından yakalanmalı
         # ama yine de bir güvenlik katmanı olarak kalabilir.
         print(f"HATA: Savaş #{battle.id} AJAX ile başlatılırken beklenmedik hata oluştu! {e_run}")
         # Durumu ERROR yap
         battle.status = CaseBattle.BattleStatus.ERROR
         battle.finished_at = timezone.now()
         battle.save(update_fields=['status', 'finished_at'])
         return JsonResponse({'success': False, 'error': 'Savaş başlatılırken sunucu hatası.', 'battle_status': battle.status })


# --- Savaş Sonuçlarını Getirme AJAX ---
@login_required
def get_battle_results_ajax(request, battle_id):
    battle = get_object_or_404(CaseBattle.objects.prefetch_related('participants__user_profile__user', 'participants__unboxings__unboxed_skin__rarity'), pk=battle_id)
    # Sadece FINISHED veya ERROR durumundaki sonuçları döndürür
    if battle.status not in [CaseBattle.BattleStatus.FINISHED, CaseBattle.BattleStatus.ERROR]:
        return JsonResponse({'success': False, 'error': 'Savaş sonuçları henüz hazır değil.'})
    participants_data = []
    placeholder_url = static('img/placeholder.png') # Placeholder URL
    for p in battle.participants.all():
        unboxings = []
        for ub in p.unboxings.all():
            rarity_info = ub.unboxed_skin.rarity
            unboxings.append({
                'id': ub.unboxed_skin.id,
                'name': ub.unboxed_skin.name,
                'image_url': ub.unboxed_skin.image_url or placeholder_url, # Placeholder kullan
                'rarity_color': rarity_info.color_hex if rarity_info else '#FFFFFF',
                'value': float(ub.unboxed_skin.value), # JS için float
                'rarity_name': rarity_info.name if rarity_info else 'common'
            })
        participants_data.append({
            'id': p.id, 'name': p.get_display_name(), 'is_bot': p.is_bot,
            'total_value': float(p.total_unboxed_value), # JS için float
            'is_winner': p.is_winner,
            'unboxings': unboxings
        })
    return JsonResponse({ 'success': True, 'participants': participants_data })