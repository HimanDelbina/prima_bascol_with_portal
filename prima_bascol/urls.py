from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.shortcuts import redirect

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('core/', include('core.urls')),
    path('masterdata/', include('masterdata.urls')),
    path('weighbridge/', include('weighbridge.urls')),
    path('reports/', include('reports.urls')),
    path('audit/', include('audit.urls')),
    path('dashboard/', include('dashboard.urls')),
    path('management/', include('management.urls')),
    path('monitoring/', include('monitoring.urls')),
    path('', lambda request: redirect('dashboard:index'), name='home'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
