from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse_lazy

from core.audit import form_changes, log_action
from core.models import AuditLog

from .forms import LoginForm, ProfileForm, StyledPasswordChangeForm


class LoginView(auth_views.LoginView):
    template_name = "registration/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


class LogoutView(auth_views.LogoutView):
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        messages.info(request, "You have been signed out.")
        return response


@login_required
def profile(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        changes = form_changes(form)
        form.save()
        log_action(request.user, AuditLog.Action.UPDATE, request.user, "Updated own profile", changes, request)
        messages.success(request, "Your profile has been updated.")
        return redirect("accounts:profile")
    recent_activity = AuditLog.objects.filter(user=request.user).order_by("-created_at")[:8]
    return render(request, "accounts/profile.html", {"form": form, "recent_activity": recent_activity})


class PasswordChangeView(auth_views.PasswordChangeView):
    template_name = "accounts/password_change.html"
    form_class = StyledPasswordChangeForm
    success_url = reverse_lazy("accounts:profile")

    def form_valid(self, form):
        response = super().form_valid(form)
        log_action(self.request.user, AuditLog.Action.UPDATE, self.request.user, "Changed password", request=self.request)
        messages.success(self.request, "Your password has been changed.")
        return response
