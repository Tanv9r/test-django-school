from django.utils import timezone
from django.utils.functional import SimpleLazyObject

from .models import HospitalSettings


def hms(request):
    context = {
        "hospital": SimpleLazyObject(HospitalSettings.load),
        "local_tz": timezone.get_current_timezone_name(),
    }
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        from accounts.permissions import capabilities_for
        from dashboard.notifications import build_notifications

        context["can"] = capabilities_for(user)
        context["notifications"] = SimpleLazyObject(lambda: build_notifications(user))
    return context
