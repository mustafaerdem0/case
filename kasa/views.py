# --- File: kasa/views.py (Yeniden Formatlanmış - Alt Alta - DÜZELTİLMİŞ) ---

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseBadRequest, Http404
from django.db import transaction, models
from django.urls import reverse
from django.db.models import Sum, Q, Min, Max, F
from django.contrib import messages
from django.utils import timezone
from django.templatetags.static import static # static import edildi
import json
from django.core.serializers.json import DjangoJSONEncoder

from .models import (Case, Skin, UserProfile, CaseSkin, UserInventoryItem, UpgradeAttempt,
                     CaseBattle, CaseBattleParticipant, CaseBattleUnboxing, Rarity)
from .forms import CreateCaseBattleForm

import random
import decimal
import logging # Loglama için

# Logger konfigürasyonu (isteğe bağlı, daha detaylı loglama için)
logger = logging.getLogger(__name__)

# === Temel View'lar ===

def home(request):
    active_cases = Case.objects.filter(is_active=True)
    context = {'cases': active_cases}
    return render(request, 'kasalar.html', context)

def case_detail(request, case_id):
    case = get_object_or_404(Case, pk=case_id, is_active=True)
    possible_skins = CaseSkin.objects.filter(case=case).select_related('skin', 'skin__rarity').order_by('-probability')

    # Placeholder resim URL'sini burada alalım
    try:
        placeholder_img_url = static('img/placeholder.png')
    except Exception:
        logger.warning("Placeholder resmi 'static/img/placeholder.png' bulunamadı.")
        placeholder_img_url = '' # Veya varsayılan bir URL

    ajax_open_url = reverse('open_case_ajax', args=[case.id])
    context = {
        'case': case,
        'possible_skins': possible_skins,
        'ajax_open_url': ajax_open_url,
        'placeholder_img_url': placeholder_img_url, # Placeholder'ı context'e ekle
    }
    return render(request, 'kasa_ac.html', context)

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

    # Placeholder URL
    try:
        placeholder_img_url = static('img/placeholder.png')
    except Exception:
        placeholder_img_url = ''

    potential_targets = []
    skins_for_upgrade = Skin.objects.filter(
        value__gt=0
    ).exclude(id__in=owned_skin_ids).select_related('rarity').order_by('value')

    for skin in skins_for_upgrade:
         rarity = skin.rarity
         potential_targets.append({
             'id': skin.id,
             'name': skin.name,
             'image_url': skin.image_url or placeholder_img_url, # Placeholder kullan
             'rarity_color': rarity.color_hex if rarity else '#FFFFFF',
             'rarity_name': rarity.name if rarity else 'common',
             'value': skin.value
         })

    calculate_url = reverse('calculate_upgrade_ajax')
    perform_url = reverse('perform_upgrade_ajax')
    context = {
        'inventory': user_inventory,
        'potential_targets': potential_targets, # Liste olarak gönder
        'potential_targets_json': json.dumps(potential_targets, cls=DjangoJSONEncoder), # JS için JSON
        'calculate_url': calculate_url,
        'perform_url': perform_url,
        'profile': user_profile,
        'placeholder_img_url': placeholder_img_url,
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
    probabilities = [max(0, cs.probability) for cs in case_skins_data]
    total_prob = sum(probabilities)

    won_skin = None
    if total_prob <= 0:
        logger.warning(f"Kasa ID {case.id} için olasılıklar toplamı {total_prob}. Rastgele seçiliyor.")
        won_skin = random.choice(skins) if skins else None
    else:
        # Olasılık normalizasyonu (eğer 1'den farklıysa) isteğe bağlı olarak yapılabilir
        if not (0.95 < total_prob < 1.05):
             logger.warning(f"Kasa ID {case.id} prob toplamı ({total_prob}) 1'den farklı!")
             # İsteğe bağlı: weights = [p / total_prob for p in probabilities]
        try:
            won_skin = random.choices(skins, weights=probabilities, k=1)[0]
        except (IndexError, ValueError) as e:
             logger.error(f"Hata: random.choices - {e}. Kasa ID: {case.id}, Olasılıklar: {probabilities}")
             won_skin = random.choice(skins) if skins else None # Fallback

    if not won_skin:
        logger.error(f"Kasa ID {case.id} için skin seçilemedi.")
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
    try:
        placeholder_img_url = static('img/placeholder.png')
    except Exception:
        placeholder_img_url = ''

    reel_length = 50
    reel_items_data = []
    possible_reel_skins = list(case_skins_data)
    for _ in range(reel_length - 1): # Kazanan hariç
        chosen_cs = random.choice(possible_reel_skins)
        rarity = chosen_cs.skin.rarity
        reel_items_data.append({
            'id': chosen_cs.skin.id,
            'name': chosen_cs.skin.name,
            'image_url': chosen_cs.skin.image_url or placeholder_img_url, # Placeholder kullan
            'rarity_color': rarity.color_hex if rarity else '#FFFFFF',
            'rarity_name': rarity.name if rarity else 'N/A'
        })

    winner_index = 40 # Kazananın reeldeki indexi
    won_skin_rarity = won_skin.rarity
    reel_items_data.insert(winner_index, {
        'id': won_skin.id,
        'name': won_skin.name,
        'image_url': won_skin.image_url or placeholder_img_url, # Placeholder kullan
        'rarity_color': won_skin_rarity.color_hex if won_skin_rarity else '#FFFFFF',
        'rarity_name': won_skin_rarity.name if won_skin_rarity else 'N/A'
    })

    return JsonResponse({
        'success': True,
        'reel_items': reel_items_data,
        'winner_index': winner_index,
        'won_skin': {
            'name': won_skin.name,
            'image_url': won_skin.image_url or placeholder_img_url,
            'rarity_name': won_skin_rarity.name if won_skin_rarity else 'N/A',
            'rarity_color': won_skin_rarity.color_hex if won_skin_rarity else '#FFFFFF'
        },
        'new_balance': user_profile.balance
    })


@login_required
def update_trade_url_ajax(request):
    if request.method != 'POST':
        return HttpResponseBadRequest("Sadece POST.")
    try:
        new_trade_url = request.POST.get('trade_url', '').strip()
        if not new_trade_url or not new_trade_url.startswith('https://steamcommunity.com/tradeoffer/new/'):
             # URL'yi daha detaylı validate etmek gerekebilir (regex vs)
            return JsonResponse({'success': False, 'error': 'Geçersiz veya eksik Steam Takas URL formatı.'})

        profile = request.user.profile
        profile.trade_url = new_trade_url
        profile.save(update_fields=['trade_url'])
        logger.info(f"Kullanıcı {request.user.username} takas URL'sini güncelledi.")
        return JsonResponse({'success': True, 'message': 'Takas URL başarıyla güncellendi.'})
    except UserProfile.DoesNotExist:
        logger.warning(f"Takas URL güncellenemedi, profil bulunamadı: {request.user.username}")
        return JsonResponse({'success': False, 'error': 'Profil bulunamadı.'})
    except Exception as e:
        logger.error(f"Trade URL güncelleme hatası ({request.user.username}): {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': 'URL güncellenirken bir sunucu hatası oluştu.'})


def calculate_upgrade_chance(input_val, target_val):
    if not isinstance(input_val, decimal.Decimal): input_val = decimal.Decimal(input_val)
    if not isinstance(target_val, decimal.Decimal): target_val = decimal.Decimal(target_val)

    if target_val <= 0 or input_val <= 0:
        return 0.0

    ratio = float(input_val / target_val)
    # Şans hesaplama formülü (sabit veya dinamik olabilir)
    multiplier = 0.85 # Örnek çarpan
    chance = ratio * multiplier
    # Min %1, Max %90 şans sınırı
    return max(0.01, min(chance, 0.90))


@login_required
def calculate_upgrade_ajax(request):
    if request.method != 'POST':
        return HttpResponseBadRequest("Sadece POST.")
    try:
        data = json.loads(request.body)
        input_ids = data.get('input_item_ids', [])
        target_id = data.get('target_skin_id')

        if not input_ids or not target_id:
            return JsonResponse({'success': False, 'error': 'Yükseltmek için en az bir eşya ve bir hedef seçmelisiniz.'})
        if not isinstance(input_ids, list):
            return JsonResponse({'success': False, 'error': 'Geçersiz girdi formatı.'})

        profile = request.user.profile
        # Seçilen ID'lerin gerçekten kullanıcıya ait ve 'AVAILABLE' olup olmadığını kontrol et
        items = UserInventoryItem.objects.filter(
            user_profile=profile,
            id__in=input_ids,
            status=UserInventoryItem.ItemStatus.AVAILABLE
        )

        if len(input_ids) != items.count():
            logger.warning(f"Calculate Upgrade: Kullanıcı {profile.user.username} geçersiz/kullanılamaz item seçti. Seçilen: {input_ids}, Bulunan: {[i.id for i in items]}")
            return JsonResponse({'success': False, 'error': 'Seçilen eşyalar geçersiz veya şu anda kullanılamıyor.'})

        input_val = items.aggregate(total=Sum('skin__value'))['total'] or decimal.Decimal('0.00')

        target = Skin.objects.get(pk=target_id) # get_object_or_404 de kullanılabilir

        chance = calculate_upgrade_chance(input_val, target.value)

        return JsonResponse({
            'success': True,
            'chance': round(chance * 100, 2),
            'total_input_value': input_val,
            'target_skin_value': target.value
        })

    except UserProfile.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Profil bulunamadı.'})
    except Skin.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Hedef eşya bulunamadı.'})
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Geçersiz istek verisi.'})
    except Exception as e:
        logger.error(f"Calculate Upgrade Error ({request.user.username}): {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': 'Şans hesaplanırken bir hata oluştu.'})


@login_required
@transaction.atomic # Veritabanı işlemlerinin bütünlüğünü koru
def perform_upgrade_ajax(request):
    if request.method != 'POST':
        return HttpResponseBadRequest("Sadece POST.")
    try:
        data = json.loads(request.body)
        input_ids = data.get('input_item_ids', [])
        target_id = data.get('target_skin_id')

        if not input_ids or not target_id:
            return JsonResponse({'success': False, 'error': 'Yükseltmek için eşya ve hedef seçimi yapılmalı.'})
        if not isinstance(input_ids, list):
            return JsonResponse({'success': False, 'error': 'Geçersiz girdi formatı.'})

        profile = request.user.profile
        target = Skin.objects.get(pk=target_id) # Hedefin varlığını kontrol et

    except (UserProfile.DoesNotExist, Skin.DoesNotExist):
        logger.warning(f"Perform Upgrade: Profil veya hedef bulunamadı. User: {request.user.username}, TargetID: {data.get('target_skin_id')}")
        return JsonResponse({'success': False, 'error': 'Profil veya hedef eşya bulunamadı.'})
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Geçersiz istek verisi.'})
    except Exception as e: # Diğer başlangıç hataları
         logger.error(f"Perform Upgrade Başlangıç Hatası ({request.user.username}): {e}", exc_info=True)
         return JsonResponse({'success': False, 'error': 'İstek işlenirken bir hata oluştu.'})

    # === İşlem Başlangıcı (Transaction içinde) ===
    try:
        # Eşyaları kilitle (select_for_update) ve durumunu kontrol et
        items = UserInventoryItem.objects.select_for_update().filter(
            user_profile=profile,
            id__in=input_ids,
            status=UserInventoryItem.ItemStatus.AVAILABLE
        ).select_related('skin', 'skin__rarity')

        # Girdi ID sayısı ile bulunan/uygun item sayısı eşleşmeli
        if len(input_ids) != items.count():
            logger.warning(f"Perform Upgrade: Kullanıcı {profile.user.username} geçersiz/kullanımda item ile denedi. İstenen: {input_ids}, Uygun: {[i.id for i in items]}")
            return JsonResponse({'success': False, 'error': 'Seçilen eşyalar artık yükseltme için uygun değil veya başka bir işlemde kullanılıyor.'})

        input_val = items.aggregate(total=Sum('skin__value'))['total'] or decimal.Decimal('0.00')
        chance = calculate_upgrade_chance(input_val, target.value)
        rolled = random.random() # 0.0 <= rolled < 1.0
        success = rolled < chance

        # 1. Girdi itemlarının durumunu güncelle
        updated_count = items.update(status=UserInventoryItem.ItemStatus.USED_UPGRADE)
        if updated_count != len(input_ids):
             # Bu durum normalde select_for_update sayesinde olmamalı ama yine de kontrol edelim
             logger.error(f"Perform Upgrade: Item durumu güncellenemedi! User: {profile.user.username}, ItemIDs: {input_ids}, Updated: {updated_count}")
             raise transaction.TransactionManagementError("Eşya durumu güncellenirken tutarsızlık oluştu.")

        # 2. Yükseltme denemesini kaydet
        attempt = UpgradeAttempt.objects.create(
            user_profile=profile, input_value=input_val, target_skin=target,
            target_value=target.value, success_chance=chance, rolled_number=rolled,
            was_successful=success
        )
        logger.info(f"Upgrade Attempt ID {attempt.id}: User {profile.user.username}, InputVal {input_val}, Target {target.name}({target.value}), Chance {chance:.4f}, Rolled {rolled:.4f}, Success: {success}")

        # 3. Başarılıysa yeni item'ı envantere ekle
        won_skin_data = None
        if success:
            new_item = UserInventoryItem.objects.create(
                user_profile=profile, skin=target, status=UserInventoryItem.ItemStatus.AVAILABLE
            )
            logger.info(f"Upgrade Success: User {profile.user.username} won {target.name}. New Inventory ID: {new_item.id}")
            target_rarity = target.rarity
            try:
                 placeholder_img_url = static('img/placeholder.png')
            except Exception: placeholder_img_url = ''
            won_skin_data = {
                'name': target.name,
                'image_url': target.image_url or placeholder_img_url,
                'rarity_name': target_rarity.name if target_rarity else 'N/A',
                'rarity_color': target_rarity.color_hex if target_rarity else '#FFFFFF'
            }

        # 4. Başarılı yanıtı hazırla
        response_data = {
            'success': True,
            'outcome': 'successful' if success else 'failed',
            'message': f'Tebrikler! {target.name} kazandınız!' if success else 'Yükseltme başarısız.',
            'chance': round(chance * 100, 2),
            'rolled': round(rolled * 100, 2),
            'won_skin': won_skin_data # Başarısızsa None olacak
        }
        return JsonResponse(response_data)

    except Exception as e: # Transaction içindeki herhangi bir hata
        logger.error(f"Perform Upgrade İşlem Hatası ({request.user.username}): {e}", exc_info=True)
        # transaction.atomic sayesinde yapılan değişiklikler geri alınacak (item durum güncellemesi vb.)
        return JsonResponse({'success': False, 'error': 'Yükseltme işlemi sırasında beklenmedik bir sunucu hatası oluştu.'})
    # === İşlem Sonu ===


# === Kasa Savaşları View'ları ===

@login_required
def active_battles_list(request):
    battles = CaseBattle.objects.filter(
        status=CaseBattle.BattleStatus.WAITING
    ).select_related('creator__user').prefetch_related(
        'participants__user_profile__user', 'cases'
    ).order_by('-created_at')

    # Her savaş için katılımcı sayısını ve toplam maliyeti önceden hesaplayabiliriz (opsiyonel optimizasyon)
    # for battle in battles:
    #     battle.participant_count = battle.participants.count() # Veya modeldeki metodu kullan
    #     battle.total_cost = battle.get_total_cost() # Modeldeki metodu kullan

    context = {'battles': battles}
    return render(request, 'active_battles.html', context)


@login_required
@transaction.atomic
def create_battle(request):
    if request.method == 'POST':
        form = CreateCaseBattleForm(request.POST)
        if form.is_valid():
            try:
                # Kullanıcı profilini al ve bakiye kontrolü için kilitle (select_for_update)
                user_profile = UserProfile.objects.select_for_update().get(user=request.user)
            except UserProfile.DoesNotExist:
                 messages.error(request,"Profil bulunamadı.")
                 return render(request, 'create_battle.html', {'form': form})

            selected_cases = form.cleaned_data['cases']
            mode = form.cleaned_data['mode']
            max_participants = int(form.cleaned_data['max_participants'])
            total_cost = sum(case.price for case in selected_cases)

            if user_profile.balance < total_cost:
                messages.error(request, f"Yetersiz bakiye! Bu savaş için {total_cost:.2f} ₺ gereklidir. Mevcut bakiyeniz: {user_profile.balance:.2f} ₺")
                return render(request, 'create_battle.html', {'form': form})

            try:
                # Bakiyeyi düşür
                user_profile.balance -= total_cost
                user_profile.save(update_fields=['balance'])

                # Savaşı oluştur
                new_battle = CaseBattle.objects.create(
                    creator=user_profile,
                    mode=mode,
                    max_participants=max_participants
                )
                new_battle.cases.set(selected_cases) # ManyToMany ilişkiyi kur

                # Kurucuyu katılımcı olarak ekle
                CaseBattleParticipant.objects.create(
                    battle=new_battle,
                    user_profile=user_profile,
                    is_bot=False
                )

                logger.info(f"Kullanıcı {user_profile.user.username} yeni savaş oluşturdu: ID {new_battle.id}, Mod: {mode}, MaxP: {max_participants}, Cost: {total_cost}")
                messages.success(request, "Savaş başarıyla oluşturuldu!")
                return redirect('battle_detail', battle_id=new_battle.id)

            except Exception as e:
                 # transaction.atomic sayesinde bakiye düşürme işlemi geri alınacak
                 logger.error(f"Savaş oluşturma DB hatası ({user_profile.user.username}): {e}", exc_info=True)
                 messages.error(request, "Savaş oluşturulurken beklenmedik bir veritabanı hatası oluştu. Lütfen tekrar deneyin.")
                 return render(request, 'create_battle.html', {'form': form}) # Hatalı formu tekrar göster
        else: # Form geçerli değilse
             messages.error(request, "Lütfen formdaki hataları düzeltin.")
             # Hatalı formu tekrar göster
             return render(request, 'create_battle.html', {'form': form})
    else: # GET request
        form = CreateCaseBattleForm()
        context = {'form': form}
        return render(request, 'create_battle.html', context)


@login_required
def battle_detail(request, battle_id):
     try:
         battle = get_object_or_404(
             CaseBattle.objects.select_related('creator__user').prefetch_related(
                 'participants__user_profile__user',
                 'cases__skins__rarity', # Kasa içindeki skinlerin rarity'leri
                 'participants__unboxings__unboxed_skin__rarity' # Açılan skinlerin rarity'leri
             ),
             pk=battle_id
         )
     except Http404:
         messages.error(request, f"Savaş #{battle_id} bulunamadı.")
         return redirect('active_battles_list')

     user_profile = None
     is_creator = False
     is_participant = False
     if request.user.is_authenticated and hasattr(request.user, 'profile'):
        try:
            user_profile = request.user.profile
            is_creator = (battle.creator == user_profile) if battle.creator else False
            is_participant = battle.participants.filter(user_profile=user_profile, is_bot=False).exists()
        except UserProfile.DoesNotExist:
            # Kullanıcının profili olmayabilir (nadiren)
            logger.warning(f"Savaş detayı görüntüleyen kullanıcının profili yok: {request.user.username}")
            pass

     participant_count = battle.get_participant_count() # Gerçek + Bot
     is_full = participant_count >= battle.max_participants # >= kullanmak daha güvenli

     # Katılma, Bot Ekleme, Başlatma Koşulları
     can_join = battle.status == CaseBattle.BattleStatus.WAITING and not is_full and not is_participant and user_profile is not None
     can_add_bot = is_creator and battle.status == CaseBattle.BattleStatus.WAITING and not is_full
     can_start_battle = is_creator and battle.status == CaseBattle.BattleStatus.WAITING and is_full

     # Kazananlar ve Ortak Mod
     # --- HATA DÜZELTMESİ: 'winners' başlangıçta QuerySet veya liste olabilir ---
     winners_qs = battle.participants.filter(is_winner=True) if battle.status == CaseBattle.BattleStatus.FINISHED else CaseBattleParticipant.objects.none()
     # 'winners' değişkenini template'de kullanmak için liste yapalım (veya QuerySet bırakalım?)
     # Şimdilik QuerySet bırakalım, template'de .all ile iterate edilir.
     winners = winners_qs # Template'e QuerySet olarak gönderelim
     multiple_winners = winners.count() > 1 # QuerySet üzerinde count() doğru çalışır

     value_per_participant = None
     if battle.status == CaseBattle.BattleStatus.FINISHED and battle.mode == CaseBattle.BattleMode.SHARED:
        real_participant_count = battle.participants.filter(is_bot=False).count() # get_real_participant_count metodu yerine direkt filtreleme
        if real_participant_count > 0:
            try:
                # Quantize ile doğru yuvarlama
                value_per_participant = (battle.total_value / decimal.Decimal(real_participant_count)).quantize(decimal.Decimal("0.01"), rounding=decimal.ROUND_DOWN)
            except (decimal.InvalidOperation, decimal.DivisionByZero):
                 logger.error(f"Savaş #{battle.id} Ortak mod değer hesaplama hatası. Toplam Değer: {battle.total_value}, Katılımcı: {real_participant_count}")
                 value_per_participant = decimal.Decimal('0.00')

     # Sütun Genişliği (Bootstrap için)
     col_lg_class_value = 12 // max(1, participant_count) # Basit hesaplama
     if participant_count > 4: col_lg_class_value = 3
     elif participant_count == 3: col_lg_class_value = 4
     elif participant_count == 2: col_lg_class_value = 6
     elif participant_count == 1: col_lg_class_value = 12


     # Animasyon için olası skinler (JS'e gönderilecek JSON)
     possible_skins_json = '[]'
     try:
         placeholder_img_url = static('img/placeholder.png')
     except Exception:
         placeholder_img_url = ''
         logger.warning("Battle Detail: Placeholder resmi bulunamadı.")

     try:
         possible_skins_in_battle = []
         seen_skin_ids = set()
         # Savaştaki TÜM kasaların içindeki TÜM skinleri topla
         skins_query = Skin.objects.filter(cases__in=battle.cases.all()).distinct().select_related('rarity')

         for skin in skins_query:
              # if skin.id not in seen_skin_ids: # distinct() kullandığımız için gereksiz olabilir
                    rarity = skin.rarity
                    possible_skins_in_battle.append({
                        'id': skin.id,
                        'name': skin.name,
                        'image_url': skin.image_url or placeholder_img_url,
                        'rarity_color': rarity.color_hex if rarity else '#FFFFFF',
                        'rarity_name': rarity.name if rarity else 'common',
                        'value': skin.value # Float olarak göndermek JS için daha kolay olabilir
                    })
                    # seen_skin_ids.add(skin.id) # distinct() kullandığımız için gereksiz olabilir

         # Değere göre sıralama (opsiyonel, JS'de de yapılabilir)
         # possible_skins_in_battle.sort(key=lambda x: x['value'])

         possible_skins_json = json.dumps(possible_skins_in_battle, cls=DjangoJSONEncoder)
     except Exception as e:
         logger.error(f"Hata: possible_skins_json oluşturulamadı - Savaş ID {battle.id}: {e}", exc_info=True)
         possible_skins_json = '[]' # Hata durumunda JS'in bozulmaması için boş liste


     context = {
         'battle': battle,
         'is_creator': is_creator,
         'is_participant': is_participant,
         'can_join': can_join,       # Katılma butonu için (view henüz katılma işlemi yapmıyor)
         'can_add_bot': can_add_bot, # Bot ekleme butonu için
         'can_start_battle': can_start_battle, # Savaş başlatma butonu için
         'winners': winners,         # Sonuçlar için (QuerySet olarak gönderiliyor)
         'multiple_winners': multiple_winners, # Sonuçlar için
         'value_per_participant': value_per_participant, # Ortak mod sonucu için
         'col_lg_class_value': col_lg_class_value,     # Sonuç kartlarının genişliği için
         'possible_skins_json': possible_skins_json,   # Animasyon için
         'max_participants': battle.max_participants, # JS'in bilmesi için
         'csrf_token': request.COOKIES.get('csrftoken'), # CSRF token'ı JS'e vermek için (form olmasa da lazım)
     }
     return render(request, 'battle_detail.html', context)


# --- Yardımcı Kasa Açma Fonksiyonu (Savaş için) ---
def _perform_single_unboxing(case: Case) -> Skin | None:
    """Verilen kasadan olasılıklara göre bir skin seçer."""
    # select_related ile skin ve rarity bilgilerini de çekelim
    case_skins_data = CaseSkin.objects.filter(case=case).select_related('skin', 'skin__rarity')
    if not case_skins_data:
        logger.warning(f"Savaşta Kasa Açma: Kasa ID {case.id} içinde skin bulunamadı.")
        return None

    skins = []
    probabilities = []
    for cs in case_skins_data:
        if cs.skin: # Skin silinmiş veya null değilse ekle
            skins.append(cs.skin)
            probabilities.append(max(0, cs.probability)) # Negatif olasılık olmasın
        else:
            logger.warning(f"Savaşta Kasa Açma: CaseSkin ID {cs.id} (Kasa ID {case.id}) ilişkili skin bulunamadı.")


    if not skins: # Eğer geçerli skin kalmadıysa
        logger.warning(f"Savaşta Kasa Açma: Kasa ID {case.id} için geçerli skin bulunamadı (ilişkili skinler null/silinmiş olabilir).")
        return None

    total_prob = sum(probabilities)

    # Olasılık kontrolü ve seçim
    if total_prob <= 0:
        logger.warning(f"Savaşta Kasa Açma: Kasa ID {case.id} için olasılıklar toplamı {total_prob}. Rastgele seçiliyor.")
        return random.choice(skins)
    elif not (0.95 < total_prob < 1.05): # Toleranslı olasılık kontrolü
        logger.warning(f"Savaşta Kasa Açma: Kasa ID {case.id} prob toplamı ({total_prob}) 1'den farklı! Olasılıklar: {probabilities}")
        # Olasılıkları normalize etmeyi düşünebiliriz ama şimdilik devam edelim
        # weights = [p / total_prob for p in probabilities]

    try:
        # random.choices weights ile olasılıklı seçim yapar
        return random.choices(skins, weights=probabilities, k=1)[0]
    except (IndexError, ValueError) as e:
        # Bu hata normalde olmamalı (eğer skins listesi boş değilse ve weights geçerliyse)
        logger.error(f"Hata: Savaşta Kasa Açma (random.choices) - {e}. Kasa ID: {case.id}, Skins: {[s.id for s in skins]}, Probs: {probabilities}", exc_info=True)
        # Hata durumunda rastgele bir skin döndür
        return random.choice(skins)


# --- SAVAŞ MANTIĞINI ÇALIŞTIRAN ANA FONKSİYON ---
@transaction.atomic # Tüm işlemlerin tek bir transaction'da yapılmasını sağla
def run_and_finalize_battle(battle: CaseBattle):
    """Savaşı yürütür, kazananı belirler ve ödülleri dağıtır."""
    logger.info(f"--- Savaş #{battle.id} Mantığı Çalıştırılıyor (Durum: {battle.status}, Mod: {battle.mode}) ---")

    # Sadece 'WAITING' durumundaki savaşlar başlatılabilir
    if battle.status != CaseBattle.BattleStatus.WAITING:
        logger.warning(f"Savaş #{battle.id} zaten başlatılmış/bitmiş/iptal edilmiş ({battle.status}). İşlem durduruldu.")
        # Belki mevcut durumu veya None döndürmek daha iyi olabilir. Şimdilik None.
        return None # Veya {'error': 'Savaş zaten işlendi'}

    # Durumu 'STARTING' yap ve başlama zamanını kaydet
    battle.status = CaseBattle.BattleStatus.STARTING
    battle.started_at = timezone.now()
    battle.save(update_fields=['status', 'started_at'])
    logger.info(f"Savaş #{battle.id} durumu STARTING olarak güncellendi.")

    unboxing_results_for_js = {} # { "participant_id_str": [skin_dict, ...], ... }
    all_unboxed_skins_pks = [] # Tüm açılan skinlerin PK'ları (kazanana vermek için)
    participants = list(battle.participants.select_related('user_profile__user').all()) # Katılımcıları al
    cases_in_battle = list(battle.cases.all()) # Savaş kasalarını al
    unboxings_to_create = [] # Toplu insert için liste

    try:
        # 1. Kasaları Aç (Her katılımcı için her kasayı)
        logger.info(f"Savaş #{battle.id}: Kasa açılışları başlıyor ({len(participants)} katılımcı, {len(cases_in_battle)} kasa)...")
        for participant in participants:
            participant_total_value = decimal.Decimal('0.00')
            participant_unboxings_for_js = [] # Bu katılımcının JS sonucu

            for case in cases_in_battle:
                won_skin = _perform_single_unboxing(case)
                if won_skin:
                    # Toplu create için Unboxing nesnesi oluştur
                    unboxings_to_create.append(
                        CaseBattleUnboxing(
                            battle_participant=participant,
                            case=case,
                            unboxed_skin=won_skin
                            # unboxed_at otomatik ekleniyor (default=timezone.now)
                        )
                    )
                    # Değerleri topla
                    participant_total_value += won_skin.value
                    all_unboxed_skins_pks.append(won_skin.pk) # Kazanan için PK sakla

                    # JS için veri hazırla
                    rarity = won_skin.rarity
                    try:
                        placeholder_img_url = static('img/placeholder.png')
                    except Exception: placeholder_img_url = ''
                    participant_unboxings_for_js.append({
                        'id': won_skin.id,
                        'name': won_skin.name,
                        'image_url': won_skin.image_url or placeholder_img_url,
                        'rarity_color': rarity.color_hex if rarity else '#FFFFFF',
                        'rarity_name': rarity.name if rarity else 'common',
                        'value': float(won_skin.value), # JSON için float
                    })
                else:
                    # Eğer _perform_single_unboxing None dönerse (kasada skin yoksa vs.)
                    logger.warning(f"Savaş #{battle.id}, Katılımcı {participant.id}, Kasa '{case.name}' (ID {case.id}) açılamadı veya skin bulunamadı.")

            # Katılımcının toplam değerini güncelle (bulk_update için sakla)
            participant.total_unboxed_value = participant_total_value
            # JS için sonuçları sakla (participant ID'yi string key yapalım)
            unboxing_results_for_js[str(participant.id)] = participant_unboxings_for_js

        # Toplu olarak unboxing kayıtlarını veritabanına ekle
        if unboxings_to_create:
            CaseBattleUnboxing.objects.bulk_create(unboxings_to_create)
            logger.info(f"Savaş #{battle.id}: {len(unboxings_to_create)} adet unboxing kaydı oluşturuldu.")

        # 2. Savaşın Toplam Değerini Hesapla
        battle.total_value = sum(p.total_unboxed_value for p in participants)
        logger.info(f"Savaş #{battle.id}: Toplam açılan değer: {battle.total_value:.2f} ₺")

        # 3. Kazanan(lar)ı Belirle
        winners = []
        losers = []
        # Sadece gerçek kullanıcıları dikkate al (botlar kazanamaz/kaybedemez)
        real_participants = [p for p in participants if not p.is_bot and p.user_profile]
        logger.info(f"Savaş #{battle.id}: Kazanan belirleme için {len(real_participants)} gerçek katılımcı var.")

        if real_participants:
            # Katılımcıların değerlerini al
            participant_values = {p.id: p.total_unboxed_value for p in real_participants}

            if battle.mode == CaseBattle.BattleMode.STANDARD:
                max_value = max(participant_values.values()) if participant_values else decimal.Decimal('-1') # Eğer katılımcı yoksa -1
                # En yüksek değere sahip TÜM katılımcıları bul (beraberlik durumu)
                winners = [p for p in real_participants if p.total_unboxed_value == max_value and max_value >= 0]
            elif battle.mode == CaseBattle.BattleMode.UNDERDOG:
                 # Sadece 0'dan büyük değerleri dikkate alarak minimum bul
                 positive_values = [v for v in participant_values.values() if v > 0]
                 min_value = min(positive_values) if positive_values else decimal.Decimal('-1')
                 # En düşük pozitif değere sahip TÜM katılımcıları bul
                 winners = [p for p in real_participants if p.total_unboxed_value == min_value and min_value > 0]
                 # Eğer herkes 0 açtıysa veya pozitif değer yoksa, kimse kazanamaz (veya hepsi berabere?) - Şimdilik kimse kazanamaz.
                 if not winners and not positive_values and len(real_participants) > 0 :
                     logger.info(f"Savaş #{battle.id} (Underdog): Tüm gerçek katılımcılar 0 değer açtı veya pozitif değer yok. Kazanan yok.")
                     # Veya beraberlik: winners = real_participants
            elif battle.mode == CaseBattle.BattleMode.SHARED:
                 winners = real_participants # Ortak modda tüm gerçek katılımcılar teknik olarak "kazanır" (pay alır)

            # Kaybedenleri belirle
            winner_ids = {w.id for w in winners}
            losers = [p for p in real_participants if p.id not in winner_ids]

        # Kazananları logla
        if winners: logger.info(f"Savaş #{battle.id}: Kazanan(lar) belirlendi: {[w.user_profile.user.username for w in winners if w.user_profile]}")
        else: logger.info(f"Savaş #{battle.id}: Kazanan belirlenemedi veya yok (Mod: {battle.mode}).")

        # Katılımcıların 'is_winner' ve 'total_unboxed_value' alanlarını topluca güncelle
        for p in participants:
            p.is_winner = (p in winners) # Gerçek kazananlar için True olacak
        CaseBattleParticipant.objects.bulk_update(participants, ['total_unboxed_value', 'is_winner'])
        logger.info(f"Savaş #{battle.id}: Katılımcıların değer ve kazanan durumları güncellendi.")

        # 4. Ödülleri Dağıt
        logger.info(f"Savaş #{battle.id}: Ödül dağıtımı başlıyor...")
        items_to_give = [] # Toplu envanter ekleme için

        if battle.mode == CaseBattle.BattleMode.STANDARD or battle.mode == CaseBattle.BattleMode.UNDERDOG:
            # Eğer tek bir kazanan varsa ve bu bot değilse, tüm skinleri ona ver
            if len(winners) == 1 and not winners[0].is_bot:
                winner_profile = winners[0].user_profile
                items_to_give = [
                    UserInventoryItem(user_profile=winner_profile, skin_id=skin_pk, status=UserInventoryItem.ItemStatus.AVAILABLE)
                    for skin_pk in all_unboxed_skins_pks # Daha önce topladığımız tüm skin PK'ları
                ]
                if items_to_give:
                     logger.info(f"Savaş #{battle.id}: {len(items_to_give)} adet skin '{winner_profile.user.username}' kullanıcısına verilecek.")
                else:
                     logger.warning(f"Savaş #{battle.id}: Kazanan '{winner_profile.user.username}' olmasına rağmen verilecek skin bulunamadı (all_unboxed_skins_pks boş).")
            elif len(winners) > 1:
                # Beraberlik durumu - skinler kimseye verilmez (veya bölüştürülür mü?) Şimdilik verilmiyor.
                 logger.info(f"Savaş #{battle.id}: Beraberlik ({len(winners)} kazanan). Skinler dağıtılmadı.")
            elif winners and winners[0].is_bot:
                 logger.info(f"Savaş #{battle.id}: Kazanan bir bot. Skinler dağıtılmadı.")
            else: # Kazanan yoksa
                 logger.info(f"Savaş #{battle.id}: Kazanan yok. Skinler dağıtılmadı.")

            # İsteğe Bağlı: Kaybedenlere teselli ödülü?
            # consolation_skin = Skin.objects.filter(value__gt=0, value__lt=1).order_by('?').first()
            # if consolation_skin and losers:
            #     for loser in losers:
            #         items_to_give.append(UserInventoryItem(user_profile=loser.user_profile, skin=consolation_skin))
            #     logger.info(f"Savaş #{battle.id}: {len(losers)} kaybedene teselli verildi: {consolation_skin.name}")

        elif battle.mode == CaseBattle.BattleMode.SHARED:
            # Ortak modda, tüm gerçek katılımcılara (winners listesi) açılan toplam değerin eşit payı bakiye olarak eklenir
            num_real_participants = len(winners) # winners = real_participants
            if num_real_participants > 0 and battle.total_value > 0:
                value_per_winner = (battle.total_value / decimal.Decimal(num_real_participants)).quantize(
                    decimal.Decimal("0.01"), rounding=decimal.ROUND_DOWN
                )
                logger.info(f"Savaş #{battle.id}: Ortak mod. {num_real_participants} katılımcıya kişi başı {value_per_winner:.2f} ₺ bakiye eklenecek.")

                # Katılımcıların bakiyelerini F() ifadesi ile atomik olarak güncelle
                profiles_to_update_pks = [w.user_profile.pk for w in winners if w.user_profile]
                if profiles_to_update_pks:
                     updated_count = UserProfile.objects.filter(pk__in=profiles_to_update_pks).update(balance=F('balance') + value_per_winner)
                     logger.info(f"Savaş #{battle.id}: {updated_count} kullanıcının ortak mod bakiyesi güncellendi.")
            else:
                 logger.info(f"Savaş #{battle.id}: Ortak modda bakiye dağıtılacak katılımcı veya değer yok.")
            # Ortak modda skinler kimseye verilmez.

        # Toplu olarak envanter itemlarını oluştur (varsa)
        if items_to_give:
            UserInventoryItem.objects.bulk_create(items_to_give)
            logger.info(f"Savaş #{battle.id}: {len(items_to_give)} adet UserInventoryItem başarıyla oluşturuldu.")

        # 5. Durumu 'FINISHED' yap ve bitiş zamanını kaydet
        battle.status = CaseBattle.BattleStatus.FINISHED
        battle.finished_at = timezone.now()
        # total_value zaten yukarıda hesaplandı ve participants bulk_update ile kaydedildi.
        # Sadece battle'ın status, finished_at ve total_value'sunu kaydet.
        battle.save(update_fields=['status', 'finished_at', 'total_value'])
        logger.info(f"--- Savaş #{battle.id} başarıyla tamamlandı (Durum: FINISHED) ---")

        # Başarılı olursa JS için hazırlanan sonuçları döndür
        return unboxing_results_for_js

    except Exception as e_run:
        # Savaş yürütme sırasında beklenmedik bir hata oluşursa
        logger.error(f"HATA: Savaş #{battle.id} yürütülürken kritik hata oluştu! {e_run}", exc_info=True)
        # Durumu 'ERROR' yap ve kaydet
        battle.status = CaseBattle.BattleStatus.ERROR
        battle.finished_at = timezone.now()
        try:
             # Hata durumunda bile status ve finished_at'ı kaydetmeye çalış
             battle.save(update_fields=['status', 'finished_at'])
        except Exception as e_save_error:
             logger.error(f"HATA: Savaş #{battle.id} ERROR durumuna güncellenirken hata oluştu! {e_save_error}", exc_info=True)

        # Hata durumunda None döndürerek AJAX view'ına hata olduğunu bildir
        return None
# --- --- --- --- --- --- --- --- --- --- --- ---


# --- Bot Ekleme AJAX ---
@login_required
@transaction.atomic # Bot ekleme de atomik olmalı
def add_bot_to_battle_ajax(request, battle_id):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'İstek yöntemi POST olmalı.'}, status=405)

    try:
        # Savaşın varlığını ve durumunu kontrol et, kilitle (select_for_update)
        battle = CaseBattle.objects.select_for_update().get(pk=battle_id)
        user_profile = request.user.profile # Kurucu kontrolü için
    except CaseBattle.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Belirtilen savaş bulunamadı.'}, status=404)
    except UserProfile.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Profiliniz bulunamadı.'}, status=403)
    except Exception as e:
        logger.error(f"Bot ekleme başlangıç hatası (Savaş ID {battle_id}): {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': 'Savaş bilgileri alınırken hata oluştu.'}, status=500)


    # Yetki kontrolü: Sadece kurucu bot ekleyebilir
    if battle.creator != user_profile:
        logger.warning(f"Yetkisiz bot ekleme denemesi: User {user_profile.user.username}, Battle ID {battle.id}")
        return JsonResponse({'success': False, 'error': 'Bot ekleme yetkiniz yok (sadece kurucu ekleyebilir).'}, status=403)

    # Durum kontrolü: Savaş dolu mu veya katılım beklenmiyor mu?
    # Not: battle.is_joinable() metodu hem durumu hem doluluğu kontrol ediyor olmalı
    if not battle.is_joinable():
        logger.warning(f"Bot ekleme başarısız: Savaş #{battle.id} dolu veya katılım beklenmiyor (Durum: {battle.status}, Katılımcı: {battle.get_participant_count()}/{battle.max_participants}).")
        # Duruma göre daha spesifik mesajlar verilebilir
        current_participants = battle.get_participant_count()
        is_full = current_participants >= battle.max_participants
        error_msg = 'Savaş zaten dolu.' if is_full else 'Savaş bot eklemeye uygun durumda değil (Başlamış/Bitmiş?).'
        return JsonResponse({'success': False, 'error': error_msg}, status=400)

    # === İşlem Başlangıcı (Transaction içinde) ===
    try:
        # Bot katılımcıyı oluştur
        new_bot = CaseBattleParticipant.objects.create(
            battle=battle,
            user_profile=None, # Botların profili olmaz
            is_bot=True
        )
        logger.info(f"Bot eklendi: Battle ID {battle.id}, Bot Participant ID {new_bot.id}")

        # Mevcut katılımcı sayısını tekrar al (yeni bot dahil)
        current_participants = battle.get_participant_count() # Veya battle.participants.count()
        is_full_now = current_participants >= battle.max_participants

        # Başarı mesajı oluştur
        message = 'Bot başarıyla eklendi.'
        if is_full_now:
            message += ' Savaş şimdi başlatılabilir!'

        # Başarılı yanıtı döndür
        return JsonResponse({
            'success': True,
            'message': message,
            'participant_count': current_participants,
            'max_participants': battle.max_participants, # JS'in bilmesi için
            'is_full': is_full_now,
            'new_participant_name': new_bot.get_display_name(), # Yeni eklenen botun adını döndür
            'new_participant_id': new_bot.id,
        })

    except Exception as e:
        logger.error(f"Bot ekleme DB hatası (Savaş ID {battle.id}): {e}", exc_info=True)
        # transaction.atomic sayesinde bot ekleme geri alınacak
        return JsonResponse({'success': False, 'error': 'Bot eklenirken beklenmedik bir veritabanı hatası oluştu.'}, status=500)
    # === İşlem Sonu ===


# --- Savaşı Başlatma AJAX ---
@login_required
@transaction.atomic # Savaş başlatma da atomik olmalı
def start_battle_ajax(request, battle_id):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'İstek yöntemi POST olmalı.'}, status=405)

    try:
        # Savaşı al ve kilitle
        # Not: run_and_finalize_battle içinde tekrar kilitleme olabilir, ama burada da kontrol etmek iyi
        battle = CaseBattle.objects.select_for_update().get(pk=battle_id)
        user_profile = request.user.profile
    except CaseBattle.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Belirtilen savaş bulunamadı.'}, status=404)
    except UserProfile.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Profiliniz bulunamadı.'}, status=403)
    except Exception as e:
        logger.error(f"Savaş başlatma başlangıç hatası (Savaş ID {battle_id}): {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': 'Savaş bilgileri alınırken hata oluştu.'}, status=500)


    # Yetki kontrolü
    if battle.creator != user_profile:
        logger.warning(f"Yetkisiz savaş başlatma denemesi: User {user_profile.user.username}, Battle ID {battle.id}")
        return JsonResponse({'success': False, 'error': 'Savaşı başlatma yetkiniz yok (sadece kurucu başlatabilir).'}, status=403)

    # Durum kontrolü
    if battle.status != CaseBattle.BattleStatus.WAITING:
        logger.warning(f"Savaş başlatma başarısız: Savaş #{battle.id} 'WAITING' durumunda değil (Durum: {battle.status}).")
        return JsonResponse({'success': False, 'error': 'Savaş zaten başlatılmış, bitmiş veya iptal edilmiş.'}, status=400)

    # Doluluk kontrolü
    participant_count = battle.get_participant_count()
    if participant_count < battle.max_participants:
        logger.warning(f"Savaş başlatma başarısız: Savaş #{battle.id} henüz dolmadı ({participant_count}/{battle.max_participants}).")
        return JsonResponse({'success': False, 'error': f'Savaşın başlaması için {battle.max_participants} katılımcı gerekli ({participant_count} katılımcı var).'}, status=400)

    # === İşlem Başlangıcı (Transaction içinde) ===
    try:
        # Ana savaş yürütme fonksiyonunu çağır
        # Bu fonksiyon transaction yönetimi içeriyor ve unboxing sonuçlarını veya None döner
        unboxing_results = run_and_finalize_battle(battle)

        # Fonksiyondan sonra savaşın güncel durumunu DB'den tekrar alalım
        battle.refresh_from_db()
        final_battle_status = battle.status

        if final_battle_status == CaseBattle.BattleStatus.FINISHED and unboxing_results is not None:
             # Başarılı Tamamlanma Durumu
             logger.info(f"Savaş #{battle.id} AJAX ile başarıyla başlatıldı ve tamamlandı.")
             response_data = {
                 'success': True,
                 'message': 'Savaş başlatıldı ve tamamlandı!',
                 'battle_status': final_battle_status, # 'FINISHED'
                 'unboxing_results': unboxing_results # JS'in animasyon için kullanacağı veri
                }
             return JsonResponse(response_data)
        elif final_battle_status == CaseBattle.BattleStatus.ERROR:
            # run_and_finalize_battle içinde bir hata oluştu ve durum ERROR oldu
            logger.error(f"Savaş #{battle.id} AJAX ile başlatılırken hata oluştu (run_and_finalize_battle None döndü veya status ERROR oldu).")
            return JsonResponse({
                'success': False,
                'error': 'Savaş yürütülürken bir hata oluştu. Lütfen yönetici ile iletişime geçin.',
                'battle_status': final_battle_status # 'ERROR'
                }, status=500)
        else:
            # Beklenmeyen durum (run_and_finalize_battle None döndü ama status FINISHED/ERROR olmadı?)
             logger.error(f"Savaş #{battle.id} AJAX başlatma sonrası beklenmeyen durum: Status={final_battle_status}, Results={unboxing_results is not None}")
             return JsonResponse({
                 'success': False,
                 'error': 'Savaş başlatılırken beklenmeyen bir durum oluştu.',
                 'battle_status': final_battle_status
                 }, status=500)

    except Exception as e_ajax:
         # Bu except bloğu normalde run_and_finalize_battle içindeki try-except tarafından yakalanmalı
         # ama yine de bir güvenlik katmanı olarak kalabilir.
         logger.error(f"KRİTİK HATA: Savaş #{battle.id} AJAX ile başlatılırken beklenmedik hata oluştu! {e_ajax}", exc_info=True)
         # Durumu manuel olarak ERROR yapmaya çalış (eğer run_and_finalize_battle bunu yapmadıysa)
         if battle.status not in [CaseBattle.BattleStatus.FINISHED, CaseBattle.BattleStatus.ERROR]:
              battle.status = CaseBattle.BattleStatus.ERROR
              battle.finished_at = timezone.now()
              try: battle.save(update_fields=['status', 'finished_at'])
              except: pass # Kayıt hatası olursa yapacak bir şey yok
         return JsonResponse({'success': False, 'error': 'Savaş başlatılırken kritik bir sunucu hatası oluştu.', 'battle_status': battle.status }, status=500)
    # === İşlem Sonu ===


# --- Savaş Sonuçlarını Getirme AJAX (Bu fonksiyon kullanılmıyor gibi ama dursun) ---
@login_required
def get_battle_results_ajax(request, battle_id):
    # Bu view'ın amacı, savaş bittikten sonra sonuçları ayrı bir istekle almaksa kullanılabilir.
    # Şu anki yapıda start_battle_ajax sonuçları direkt döndürüyor.
    try:
        battle = get_object_or_404(
            CaseBattle.objects.prefetch_related(
                'participants__user_profile__user',
                'participants__unboxings__unboxed_skin__rarity' # Gerekli ilişkileri çek
            ),
            pk=battle_id
        )
    except Http404:
         return JsonResponse({'success': False, 'error': 'Savaş bulunamadı.'}, status=404)

    # Sadece bitmiş veya hatalı savaşların sonuçlarını döndür
    if battle.status not in [CaseBattle.BattleStatus.FINISHED, CaseBattle.BattleStatus.ERROR]:
        return JsonResponse({'success': False, 'error': 'Savaş sonuçları henüz hazır değil.', 'status': battle.status})

    # Placeholder URL
    try:
        placeholder_img_url = static('img/placeholder.png')
    except Exception:
        placeholder_img_url = ''

    participants_data = []
    for p in battle.participants.all():
        unboxings_data = []
        # participant ile ilişkili unboxingları çek (prefetch_related sayesinde verimli olmalı)
        for ub in p.unboxings.all():
            skin = ub.unboxed_skin
            if not skin: # İlişkili skin silinmişse atla
                 logger.warning(f"Get Battle Results: Unboxing ID {ub.id} için skin bulunamadı (Savaş {battle_id})")
                 continue
            rarity_info = skin.rarity
            unboxings_data.append({
                'id': skin.id,
                'name': skin.name,
                'image_url': skin.image_url or placeholder_img_url, # Placeholder kullan
                'rarity_color': rarity_info.color_hex if rarity_info else '#FFFFFF',
                'rarity_name': rarity_info.name if rarity_info else 'common',
                'value': float(skin.value), # JS için float
            })

        participants_data.append({
            'id': p.id,
            'name': p.get_display_name(), # Bot ise "Bot X", değilse username
            'is_bot': p.is_bot,
            'total_value': float(p.total_unboxed_value), # JS için float
            'is_winner': p.is_winner,
            'unboxings': unboxings_data # Bu katılımcının açtığı skinler
        })

    return JsonResponse({
        'success': True,
        'battle_status': battle.status,
        'participants': participants_data,
        'total_battle_value': float(battle.total_value),
        'mode': battle.mode,
    })