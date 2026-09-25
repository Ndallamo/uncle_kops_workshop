from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.views.generic import RedirectView
from django.conf import settings
from django.conf.urls.static import static
from workshop import views as workshop_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/admin/', RedirectView.as_view(url='/admin/', permanent=False)),
    path('login/admin', RedirectView.as_view(url='/admin/', permanent=False)),

    # Auth
    path('login/',  workshop_views.login_view, name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('register/', workshop_views.register, name='register'),

    # Workshop app
    path('', include('workshop.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
