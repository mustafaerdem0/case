# --- File: kasa/models.py ---

from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
import decimal

# --- Temel Modeller ---
class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    steam_id = models.CharField(max_length=100, unique=True, blank=True, null=True)
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=decimal.Decimal('0.00'))
    trade_url = models.URLField(max_length=255, blank=True, null=True, help_text="Steam Takas URL'niz")
    def __str__(self): return self.user.username

@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    if created: UserProfile.objects.create(user=instance)
    try: instance.profile.save()
    except UserProfile.DoesNotExist: UserProfile.objects.create(user=instance)

class Rarity(models.Model):
    name = models.CharField(max_length=50, unique=True)
    color_hex = models.CharField(max_length=7, default='#FFFFFF', help_text="CSS Hex kodu")
    def __str__(self): return self.name
    class Meta: verbose_name_plural = "Rarities"

class Skin(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    image_url = models.URLField(max_length=500, null=True, blank=True) # null=True, blank=True Düzeltildi
    rarity = models.ForeignKey(Rarity, on_delete=models.SET_NULL, null=True, related_name='skins')
    value = models.DecimalField(max_digits=10, decimal_places=2, default=decimal.Decimal('0.00'), help_text="Piyasa değeri")
    def __str__(self): return f"{self.name} ({self.rarity.name if self.rarity else 'N/A'})"

class Case(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    image_url = models.URLField(max_length=500, null=True, blank=True) # null=True, blank=True Eklendi
    price = models.DecimalField(max_digits=10, decimal_places=2)
    skins = models.ManyToManyField(Skin, through='CaseSkin', related_name='cases')
    is_active = models.BooleanField(default=True)
    def __str__(self): return self.name
    def get_total_value_in_case(self): return sum(cs.skin.value for cs in self.caseskin_set.all())

class CaseSkin(models.Model):
    case = models.ForeignKey(Case, on_delete=models.CASCADE)
    skin = models.ForeignKey(Skin, on_delete=models.CASCADE)
    probability = models.FloatField(help_text="Çıkma olasılığı (örn: 0.05)")
    class Meta: unique_together = ('case', 'skin'); ordering = ['-probability']
    def __str__(self): return f"{self.case.name} -> {self.skin.name} ({self.probability*100:.4f}%)"

class UserInventoryItem(models.Model):
    class ItemStatus(models.TextChoices):
        AVAILABLE = 'AVAILABLE', 'Mevcut'
        USED_UPGRADE = 'USED_UPGRADE', 'Yükseltildi'
        WITHDRAWN = 'WITHDRAWN', 'Çekildi'
        IN_BATTLE = 'IN_BATTLE', 'Savaşta' # <-- Savaş durumu Eklendi
    user_profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='inventory_items')
    skin = models.ForeignKey(Skin, on_delete=models.CASCADE)
    added_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=ItemStatus.choices, default=ItemStatus.AVAILABLE)
    def __str__(self): return f"{self.user_profile.user.username}'s {self.skin.name} ({self.get_status_display()})"
    class Meta: ordering = ['-added_at']

class UpgradeAttempt(models.Model):
    user_profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='upgrade_attempts')
    input_value = models.DecimalField(max_digits=10, decimal_places=2)
    target_skin = models.ForeignKey(Skin, on_delete=models.SET_NULL, null=True)
    target_value = models.DecimalField(max_digits=10, decimal_places=2)
    success_chance = models.FloatField()
    rolled_number = models.FloatField(null=True, blank=True)
    was_successful = models.BooleanField()
    timestamp = models.DateTimeField(auto_now_add=True)
    def __str__(self): outcome = "Başarılı" if self.was_successful else "Başarısız"; return f"{self.user_profile.user.username} -> {self.target_skin.name if self.target_skin else '?'} ({outcome}) @ {self.timestamp}"
    class Meta: ordering = ['-timestamp']

# --- Kasa Savaşları Modelleri (Tek Sefer Doğru Tanım) ---
class CaseBattle(models.Model):
    class BattleStatus(models.TextChoices): WAITING = 'WAITING', 'Katılımcı Bekleniyor'; STARTING = 'STARTING', 'Başlatılıyor'; FINISHED = 'FINISHED', 'Tamamlandı'; CANCELLED = 'CANCELLED', 'İptal Edildi'; ERROR = 'ERROR', 'Hata Oluştu'
    class BattleMode(models.TextChoices): STANDARD = 'STANDARD', 'Standart'; UNDERDOG = 'UNDERDOG', 'Underdog'; SHARED = 'SHARED', 'Ortak'
    creator = models.ForeignKey(UserProfile, related_name='created_battles', on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=10, choices=BattleStatus.choices, default=BattleStatus.WAITING)
    mode = models.CharField(max_length=10, choices=BattleMode.choices, default=BattleMode.STANDARD)
    max_participants = models.PositiveSmallIntegerField(default=2)
    cases = models.ManyToManyField(Case, related_name='battles')
    total_value = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    # --- METODLAR DOĞRU ŞEKİLDE EKLENDİ ---
    def get_total_cost(self):
        return sum(case.price for case in self.cases.all())

    def get_participant_count(self):
        # 'participants' CaseBattleParticipant modelindeki related_name'dir
        return self.participants.count()

    def get_real_participant_count(self):
        return self.participants.filter(is_bot=False).count()

    def get_bot_count(self):
        return self.participants.filter(is_bot=True).count()

    def is_joinable(self):
        # Toplam katılımcı sayısına göre kontrol eder
        return self.status == self.BattleStatus.WAITING and self.get_participant_count() < self.max_participants
    # --- --- --- --- --- --- --- --- --- --- ---

    def __str__(self): return f"Savaş #{self.id} ({self.get_status_display()})"
    class Meta: ordering = ['-created_at']

class CaseBattleParticipant(models.Model):
    battle = models.ForeignKey(CaseBattle, related_name='participants', on_delete=models.CASCADE)
    user_profile = models.ForeignKey(UserProfile, related_name='battle_participations', on_delete=models.CASCADE, null=True, blank=True) # Botlar için null olabilir
    is_bot = models.BooleanField(default=False) # Bot mu?
    total_unboxed_value = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    is_winner = models.BooleanField(default=False)
    joined_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ['joined_at'] # unique_together kaldırılmıştı

    def get_display_name(self):
        if self.is_bot:
            try: bots = list(self.battle.participants.filter(is_bot=True).order_by('id')); bot_index = bots.index(self) + 1; return f"Bot {bot_index}"
            except ValueError: return "Bot"
        elif self.user_profile: return self.user_profile.user.username
        else: return "Bilinmeyen"
    def __str__(self): return f"{self.get_display_name()} @ Savaş #{self.battle.id}"

class CaseBattleUnboxing(models.Model):
    battle_participant = models.ForeignKey(CaseBattleParticipant, related_name='unboxings', on_delete=models.CASCADE)
    case = models.ForeignKey(Case, on_delete=models.CASCADE)
    unboxed_skin = models.ForeignKey(Skin, on_delete=models.CASCADE)
    unboxed_at = models.DateTimeField(default=timezone.now)
    def __str__(self): return f"{self.battle_participant} -> {self.unboxed_skin.name} ({self.case.name})"
    class Meta: ordering = ['unboxed_at']