from django.contrib import admin
from .models import UserProfile, Rarity, Skin, Case, CaseSkin, UserInventoryItem, UpgradeAttempt

class CaseSkinInline(admin.TabularInline): model = CaseSkin; extra = 1
@admin.register(Case)
class CaseAdmin(admin.ModelAdmin): list_display = ('name', 'price', 'is_active'); list_filter = ('is_active',); search_fields = ('name',); inlines = [CaseSkinInline]
@admin.register(Rarity)
class RarityAdmin(admin.ModelAdmin): list_display = ('name', 'color_hex')
@admin.register(Skin)
class SkinAdmin(admin.ModelAdmin): list_display = ('name', 'rarity', 'value'); list_filter = ('rarity',); search_fields = ('name',)
@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin): list_display = ('user', 'steam_id', 'balance', 'trade_url'); search_fields = ('user__username', 'steam_id')
@admin.register(UserInventoryItem)
class UserInventoryItemAdmin(admin.ModelAdmin): list_display = ('user_profile', 'skin', 'status', 'added_at'); list_filter = ('status', 'added_at', 'skin__rarity'); search_fields = ('user_profile__user__username', 'skin__name'); list_editable = ('status',)
@admin.register(UpgradeAttempt)
class UpgradeAttemptAdmin(admin.ModelAdmin): list_display = ('user_profile', 'target_skin', 'input_value', 'target_value', 'success_chance', 'was_successful', 'timestamp'); list_filter = ('was_successful', 'timestamp'); search_fields = ('user_profile__user__username', 'target_skin__name'); readonly_fields = ('user_profile', 'input_value', 'target_skin', 'target_value', 'success_chance', 'rolled_number', 'was_successful', 'timestamp')
