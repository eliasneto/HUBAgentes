from django.contrib import admin

from .models import UserProfile


admin.site.site_header = "Leitura de Licitacao - Admin"
admin.site.site_title = "Leitura de Licitacao"
admin.site.index_title = "Gestao operacional"


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "papel_principal", "updated_at")
    search_fields = ("user__username", "user__email", "user__first_name", "user__last_name")
