from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

class BakiyeEklemeFormu(forms.Form):
    miktar = forms.DecimalField(label="Eklemek İstediğiniz Miktar")

class KayitFormu(UserCreationForm):
    class Meta:
        model = User
        fields = ('username', 'email')  # İstediğiniz alanları ekleyincls
        
# --- File: kasa/forms.py ---

# kasa/forms.py

from django import forms
from .models import Case, CaseBattle

class CreateCaseBattleForm(forms.Form):
    mode = forms.ChoiceField(
        choices=CaseBattle.BattleMode.choices,
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        label="Savaş Modu", initial=CaseBattle.BattleMode.STANDARD, required=True,
    )
    participant_choices = [(i, f"{i} Kişi") for i in range(2, 5)]
    max_participants = forms.ChoiceField(
        choices=participant_choices,
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        label="Toplam Katılımcı Sayısı", initial=2, required=True,
    )
    # Bot seçimi kaldırıldı
    cases = forms.ModelMultipleChoiceField(
        queryset=Case.objects.filter(is_active=True).order_by('price'),
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input case-select-checkbox'}),
        label="Savaşa Eklenecek Kasalar", required=True,
        error_messages={'required': 'Lütfen savaşa en az bir kasa ekleyin.'}
    )

    def clean(self):
        # Bot ile ilgili validasyon kaldırıldı
        cleaned_data = super().clean()
        selected_cases = cleaned_data.get("cases")
        if not selected_cases:
             self.add_error('cases', 'Lütfen savaşa en az bir kasa ekleyin.')
        elif len(selected_cases) > 10:
            self.add_error('cases', "Bir savaş için en fazla 10 kasa seçebilirsiniz.")
        return cleaned_data