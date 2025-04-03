from django.db import models
from django.contrib.auth.models import User

class Kasa(models.Model):
    ad = models.CharField(max_length=200)
    fiyat = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return self.ad

class Skin(models.Model):
    ad = models.CharField(max_length=200)
    resim = models.ImageField(upload_to='skinler/')
    fiyat = models.DecimalField(max_digits=10, decimal_places=2)
    kasa = models.ForeignKey(Kasa, on_delete=models.CASCADE)
    nadirlik = models.CharField(max_length=50, default='Common')  # Nadirlik alanı ekledik

    def __str__(self):
        return self.ad

class KullaniciProfili(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    bakiye = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def __str__(self):
        return self.user.username

class KazanilanSkin(models.Model):
    kullanici = models.ForeignKey(User, on_delete=models.CASCADE)
    skin = models.ForeignKey(Skin, on_delete=models.CASCADE)
    kazanma_tarihi = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.kullanici.username} - {self.skin.ad}"