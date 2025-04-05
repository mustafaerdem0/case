from django.apps import AppConfig

class KasaConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'kasa' # Uygulama adı

    def ready(self):
        # Sinyalleri burada import et
        import kasa.models # veya from . import models -> models.py içindeki sinyaller yüklenir