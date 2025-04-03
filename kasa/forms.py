from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

class BakiyeEklemeFormu(forms.Form):
    miktar = forms.DecimalField(label="Eklemek İstediğiniz Miktar")

class KayitFormu(UserCreationForm):
    class Meta:
        model = User
        fields = ('username', 'email')  # İstediğiniz alanları ekleyincls