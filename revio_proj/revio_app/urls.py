from django.urls import path

from . import views

urlpatterns = [
    path('', views.index, name='index'),

    # Rev.io API methods
    # path('order_info/', views.get_order_info, name='order_info'),
    path('rel_orders/', views.get_related_orders, name='rel_orders'),

    # SuperSaaS API methods
    path('available_slots/', views.get_available_slots, name='available_slots'),
    path('activation_names/', views.get_activation_names, name='activation_names'),
    # path('appointments/', views.get_appointments, name='appointments'),
    path('bookings/', views.post_bookings, name='bookings'),
    path('delete_bookings/', views.delete_bookings, name='delete_bookings'),
    path('import_appointments/', views.import_appointments, name='import_appointments')
]
