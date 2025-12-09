from django.urls import path

from .views import DeviceEventIngestView, LockerSensorEventView

urlpatterns = [
    path('events/', DeviceEventIngestView.as_view(), name='iot-events-ingest'),
    path('locker-events/', LockerSensorEventView.as_view(), name='iot-locker-events'),
]
