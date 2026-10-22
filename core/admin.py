from django.contrib import admin
from .models import Farmer, Delivery, Payment, Stock, ErrorRecord, Notification, ContactMessage

admin.site.register(Farmer)
admin.site.register(Delivery)
admin.site.register(Payment)
admin.site.register(Stock)
admin.site.register(ErrorRecord)
admin.site.register(Notification)


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'phone', 'emailed', 'created_at')
    list_filter = ('emailed', 'created_at')
    search_fields = ('name', 'email', 'message')
    readonly_fields = ('created_at',)
