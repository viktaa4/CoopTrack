from django.urls import path
from . import views

urlpatterns = [
    # public
    path('', views.landing, name='landing'),
    path('contact/', views.contact_submit, name='contact_submit'),

    # accounts
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),

    # dashboard
    path('dashboard/', views.dashboard, name='dashboard'),
    path('notifications/read/', views.notifications_read, name='notifications_read'),

    # farmers
    path('farmers/', views.farmers_view, name='farmers'),
    path('farmers/add/', views.farmer_add, name='farmer_add'),
    path('farmers/<int:pk>/', views.farmer_detail, name='farmer_detail'),
    path('farmers/<int:pk>/edit/', views.farmer_edit, name='farmer_edit'),
    path('farmers/<int:pk>/delete/', views.farmer_delete, name='farmer_delete'),

    # deliveries
    path('deliveries/', views.deliveries_view, name='deliveries'),
    path('deliveries/add/', views.delivery_add, name='delivery_add'),
    path('deliveries/<int:pk>/edit/', views.delivery_edit, name='delivery_edit'),
    path('deliveries/<int:pk>/verify/', views.delivery_verify, name='delivery_verify'),
    path('deliveries/<int:pk>/delete/', views.delivery_delete, name='delivery_delete'),

    # payments
    path('payments/', views.payments_view, name='payments'),
    path('payments/add/', views.payment_add, name='payment_add'),
    path('payments/<int:pk>/edit/', views.payment_edit, name='payment_edit'),
    path('payments/<int:pk>/paid/', views.payment_paid, name='payment_paid'),
    path('payments/<int:pk>/delete/', views.payment_delete, name='payment_delete'),

    # stock
    path('stock/', views.stock_view, name='stock'),
    path('stock/dispatch/', views.stock_dispatch, name='stock_dispatch'),
    path('stock/recalculate/', views.stock_recalc, name='stock_recalc'),

    # errors
    path('errors/', views.errors_view, name='errors'),
    path('errors/scan/', views.errors_scan, name='errors_scan'),
    path('errors/<int:pk>/status/', views.error_status, name='error_status'),

    # reports
    path('reports/', views.reports_view, name='reports'),
    path('reports/export/<str:kind>/', views.report_export, name='report_export'),
]
