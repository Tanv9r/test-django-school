from decimal import Decimal, InvalidOperation

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()

BADGE_COLORS = {
    # appointments
    "scheduled": "primary",
    "confirmed": "info",
    "completed": "success",
    "cancelled": "secondary",
    "no_show": "warning",
    # admissions & beds
    "admitted": "primary",
    "discharged": "success",
    "available": "success",
    "occupied": "danger",
    "maintenance": "warning",
    # billing
    "unpaid": "danger",
    "partially_paid": "warning",
    "paid": "success",
    # prescriptions & tasks
    "dispensed": "success",
    "pending": "warning",
    "in_progress": "info",
    "done": "success",
    # staff
    "active": "success",
    "inactive": "secondary",
    "on_leave": "warning",
    "suspended": "danger",
    "terminated": "secondary",
    # priority
    "high": "danger",
    "normal": "info",
    "low": "secondary",
}


@register.filter
def status_badge(value, label=None):
    """``{{ obj.status|status_badge:obj.get_status_display }}``"""
    color = BADGE_COLORS.get(str(value), "secondary")
    return format_html('<span class="badge badge-soft-{}">{}</span>', color, label or value)


@register.filter
def active_badge(is_active):
    if is_active:
        return mark_safe('<span class="badge badge-soft-success">Active</span>')
    return mark_safe('<span class="badge badge-soft-secondary">Inactive</span>')


@register.simple_tag(takes_context=True)
def money(context, value):
    hospital = context.get("hospital")
    symbol = getattr(hospital, "currency_symbol", "$") if hospital is not None else "$"
    try:
        amount = Decimal(value or 0)
    except (InvalidOperation, TypeError, ValueError):
        return value
    sign = "-" if amount < 0 else ""
    return f"{sign}{symbol}{abs(amount):,.2f}"


@register.simple_tag(takes_context=True)
def nav_active(context, prefix, exclude=""):
    """``{% nav_active '/admissions/' exclude='/admissions/beds/,/admissions/tasks/' %}``"""
    request = context.get("request")
    if request is None or not request.path.startswith(prefix):
        return ""
    if any(request.path.startswith(e) for e in exclude.split(",") if e):
        return ""
    return "active"


@register.filter
def initials(name):
    parts = [p for p in str(name).replace("Dr.", "").split() if p]
    return "".join(p[0] for p in parts[:2]).upper() or "?"


@register.filter
def get_item(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter
def percent(part, whole):
    try:
        return round(float(part) * 100 / float(whole)) if float(whole) else 0
    except (TypeError, ValueError, ZeroDivisionError):
        return 0
