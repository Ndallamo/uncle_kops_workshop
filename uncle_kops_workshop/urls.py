from django.contrib import admin
from django.urls import path, include, reverse_lazy
from django.contrib.auth import views as auth_views
from django.views.generic import RedirectView
from django.conf import settings
from django.conf.urls.static import static
from workshop import views as workshop_views

handler404 = 'workshop.views.custom_404'
handler500 = 'workshop.views.custom_500'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('account/password/', auth_views.PasswordChangeView.as_view(
        template_name='workshop/change_password.html',
        success_url=reverse_lazy('customer_profile'),
    ), name='password_change'),
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
