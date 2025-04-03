from django.shortcuts import render, redirect, get_object_or_404
from .forms import BakiyeEklemeFormu, KayitFormu
from .models import Kasa, Skin, KullaniciProfili, KazanilanSkin
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.http import JsonResponse
import random
from django.db import transaction

def kasalar(request):
    kasalar = Kasa.objects.all()
    kullanici_profili = None
    if request.user.is_authenticated:
        kullanici_profili = KullaniciProfili.objects.filter(user=request.user).first()
    return render(request, 'kasa/kasalar.html', {'kasalar': kasalar, 'kullanici_profili': kullanici_profili})

def kasa_ac(request, kasa_id):
    kasa = get_object_or_404(Kasa, pk=kasa_id)
    return render(request, 'kasa/kasa_ac.html', {'kasa': kasa})

@login_required
def kasa_ac_ajax(request, kasa_id):
    kasa = get_object_or_404(Kasa, pk=kasa_id)
    profil = get_object_or_404(KullaniciProfili, user=request.user)

    if profil.bakiye < kasa.fiyat:
        return JsonResponse({'hata': 'Yetersiz bakiye'}, status=400)

    skinler = Skin.objects.filter(kasa=kasa)
    kazanilan_skin = random.choice(skinler)

    # Bakiye düşme
    profil.bakiye -= kasa.fiyat
    profil.save()

    # Kazanılan skin kaydetme
    KazanilanSkin.objects.create(kullanici=request.user, skin=kazanilan_skin)

    return JsonResponse({
        'skin_resim': kazanilan_skin.resim.url
    })

@login_required
def bakiye_ekle(request):
    profil = get_object_or_404(KullaniciProfili, user=request.user)
    if request.method == "POST":
        form = BakiyeEklemeFormu(request.POST)
        if form.is_valid():
            miktar = form.cleaned_data['miktar']
            profil.bakiye += miktar
            profil.save()
            return redirect('bakiye_ekle')
        else:
          for error in form.errors.values():
            print(error)
        
    else:
        form = BakiyeEklemeFormu()
    return render(request, 'kasa/bakiye_ekle.html', {'form': form, 'profil': profil})

@login_required
def kazanilan_skinler(request):
    kazanilanlar = KazanilanSkin.objects.filter(kullanici=request.user)
    return render(request, 'kasa/kazanilan_skinler.html', {'kazanilanlar': kazanilanlar})

def ana_sayfa(request):
    return kasalar(request)

from django.db import transaction

def register(request):
    if request.method == 'POST':
        form = KayitFormu(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    user = form.save()
                    KullaniciProfili.objects.create(user=user)
                    login(request, user)
                return redirect('kasalar')
            except Exception as e:
                print(f"Hata oluştu: {e}") #opsiyonel
                return render(request, 'kasa/register.html', {'form': form, 'hata_mesaji': 'Kayıt sırasında bir hata oluştu. Lütfen tekrar deneyin.'}) #burayı düzenledim
        else:
            for error in form.errors.values():
                print(f"Form Error: {error}")
    else:
        form = KayitFormu()
    return render(request, 'kasa/register.html', {'form': form})
