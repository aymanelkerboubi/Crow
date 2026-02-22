from django.apps import AppConfig

class CrowAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'crow_app'
    # Optional: Add a verbose name
    verbose_name = "Crow Video App"