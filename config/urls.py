from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from kasa import views 
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('kasa/', views.kasalar, name='kasalar'),
    path('kasa/<int:kasa_id>/ac/', views.kasa_ac, name='kasa_ac'),
    path('kasa/<int:kasa_id>/ac_ajax/', views.kasa_ac_ajax, name='kasa_ac_ajax'),
    path('bakiye/ekle/', views.bakiye_ekle, name='bakiye_ekle'), 
    path('kazanilanlar/', views.kazanilan_skinler, name='kazanilan_skinler'), 
    path('login/', auth_views.LoginView.as_view(template_name='kasa/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='kasalar'), name='logout'),
    path('register/', views.register, name='register'),
    path('', views.kasalar, name='ana_sayfa'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)