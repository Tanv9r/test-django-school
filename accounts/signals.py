from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from core.audit import log_action
from core.models import AuditLog


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    log_action(user, AuditLog.Action.LOGIN, obj=user, message="Signed in", request=request)


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    if user is not None:
        log_action(user, AuditLog.Action.LOGOUT, obj=user, message="Signed out", request=request)


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request=None, **kwargs):
    username = str(credentials.get("username", ""))[:150]
    log_action(None, AuditLog.Action.LOGIN_FAILED, message=f"Failed sign-in for '{username}'", request=request)
