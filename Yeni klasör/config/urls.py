# config/urls.py

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from kasa import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('allauth.urls')),

    # Kasa uygulamasının URL'leri
    path('', views.home, name='home'),
    path('case/<int:case_id>/', views.case_detail, name='case_detail'),
    path('profile/', views.profile, name='profile'),
    path('deposit/', views.deposit_page, name='deposit_page'),
    path('withdraw/', views.withdraw_page, name='withdraw_page'),
    path('upgrade/', views.upgrade_page, name='upgrade_page'),

    # Kasa Savaşları URL'leri
    path('battles/', views.active_battles_list, name='active_battles_list'),
    path('battles/create/', views.create_battle, name='create_battle'),
    path('battles/<int:battle_id>/', views.battle_detail, name='battle_detail'),

    # AJAX Endpoints
    path('ajax/open_case/<int:case_id>/', views.open_case_ajax, name='open_case_ajax'),
    path('ajax/update_trade_url/', views.update_trade_url_ajax, name='update_trade_url_ajax'),
    path('ajax/calculate_upgrade/', views.calculate_upgrade_ajax, name='calculate_upgrade_ajax'),
    path('ajax/perform_upgrade/', views.perform_upgrade_ajax, name='perform_upgrade_ajax'),
    path('ajax/battle_results/<int:battle_id>/', views.get_battle_results_ajax, name='get_battle_results_ajax'),
    # --- YENİ: Bot Ekleme AJAX URL ---
    path('ajax/start_battle/<int:battle_id>/', views.start_battle_ajax, name='start_battle_ajax'),

    path('ajax/add_bot/<int:battle_id>/', views.add_bot_to_battle_ajax, name='add_bot_to_battle_ajax'),
    # --- --- --- --- --- --- --- --- ---

]

# MEDIA dosyaları
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)