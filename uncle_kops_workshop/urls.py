from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.views.generic import RedirectView
from django.conf import settings
from django.conf.urls.static import static
from workshop import views as workshop_views

handler404 = 'workshop.views.custom_404'
handler500 = 'workshop.views.custom_500'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/admin/', RedirectView.as_view(url='/admin/', permanent=False)),
    path('login/admin', RedirectView.as_view(url='/admin/', permanent=False)),

    # Auth
    path('login/',  workshop_views.login_view, name='login'),
    path('logout/', workshop_views.logout_view, name='logout'),
    path('register/', workshop_views.register, name='register'),
    path('forgot-password/', workshop_views.forgot_password, name='forgot_password'),
    path('reset-password/', workshop_views.reset_password, name='reset_password'),
    path('privacy-policy/', workshop_views.privacy_policy, name='privacy_policy'),
    path('terms-and-conditions/', workshop_views.terms_and_conditions, name='terms_and_conditions'),

    # Workshop app
    path('', include('workshop.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
