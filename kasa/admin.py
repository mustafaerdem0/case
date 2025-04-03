from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import Kasa, Skin

admin.site.register(Kasa)
admin.site.register(Skin)