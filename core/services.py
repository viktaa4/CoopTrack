"""
CoopTrack business logic.

This file holds the "brain" of the system:
  * recalc_stock()  - keeps stock figures in step with verified deliveries
  * run_checks()    - finds mistakes in the records and writes them to the Errors page
"""
import re
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from .models import Farmer, Delivery, Payment, Stock, ErrorRecord, Notification

# Kenyan mobile numbers: 07xx xxx xxx, 01xx xxx xxx, +2547xx..., 2547xx...
PHONE_RE = re.compile(r'^(?:\+?254|0)[17]\d{8}$')


def normalise_phone(value):
    """Remove spaces, dashes and brackets from a phone number."""
    return re.sub(r'[\s\-().]', '', value or '')


def phone_is_valid(value):
    return bool(PHONE_RE.match(normalise_phone(value)))


def notify(user, message):
    """Add a line to the 'Recent activity' list of a staff member."""
    if user is not None and user.is_authenticated:
        Notification.objects.create(user=user, message=message[:255])


# ----------------------------------------------------------------------
# STOCK
# ----------------------------------------------------------------------
def recalc_stock():
    """
    received  = total of all VERIFIED deliveries of that produce
    available = received - dispatched
    A negative 'available' means more was dispatched than received (Mismatch).
    """
    verified = (Delivery.objects.filter(status='Verified')
                .values('produce').annotate(total=Sum('quantity')))
    totals = {row['produce'].strip().title(): row['total'] for row in verified}

    names = {p.strip().title() for p in Delivery.objects.values_list('produce', flat=True)}
    names |= set(Stock.objects.values_list('produce', flat=True))

    for name in sorted(names):
        stock, _ = Stock.objects.get_or_create(produce=name)
        stock.received = totals.get(name, Decimal('0'))
        stock.available = stock.received - stock.dispatched
        stock.status = 'Mismatch' if stock.available < 0 else 'Verified'
        stock.save()


# ----------------------------------------------------------------------
# ERROR DETECTION
# ----------------------------------------------------------------------
def collect_issues():
    """Look through all records and return a list of problems found right now."""
    issues = []
    today = timezone.localdate()

    # 1) Farmers with a phone number that does not look right
    for farmer in Farmer.objects.exclude(status='Inactive'):
        if not phone_is_valid(farmer.phone):
            issues.append({
                'title': 'Wrong farmer information',
                'related': farmer.code,
                'desc': f"The phone number '{farmer.phone}' for {farmer.name} does not look like a valid Kenyan number.",
                'farmer': farmer,
            })

    # 2) Deliveries
    deliveries = list(Delivery.objects.select_related('farmer'))
    by_receipt = {}
    for d in deliveries:
        by_receipt.setdefault(d.receipt_no.strip().upper(), []).append(d)

    for receipt, group in by_receipt.items():
        if len(group) > 1:
            codes = ', '.join(g.code for g in group)
            for d in group:
                issues.append({
                    'title': 'Receipt mismatch',
                    'related': d.code,
                    'desc': f"Receipt {receipt} is used by more than one delivery ({codes}).",
                    'delivery': d, 'blocking': True,
                })

    for d in deliveries:
        if d.delivery_date > today:
            issues.append({
                'title': 'Wrong delivery date',
                'related': d.code,
                'desc': f"Delivery {d.code} is dated {d.delivery_date:%d %b %Y}, which is in the future.",
                'delivery': d, 'blocking': True,
            })
        recorded_on = timezone.localtime(d.created_at).date()
        if recorded_on > d.delivery_date + timedelta(days=1):
            issues.append({
                'title': 'Late delivery record',
                'related': d.code,
                'desc': f"Delivery {d.code} happened on {d.delivery_date:%d %b} but was only recorded on {recorded_on:%d %b}.",
                'delivery': d, 'blocking': False,
            })

    # 3) Payments
    for p in Payment.objects.select_related('delivery', 'farmer'):
        if p.receipt_no.strip().upper() != p.delivery.receipt_no.strip().upper():
            issues.append({
                'title': 'Receipt mismatch',
                'related': p.code,
                'desc': (f"Payment {p.code} uses receipt {p.receipt_no}, but delivery "
                         f"{p.delivery.code} has receipt {p.delivery.receipt_no}."),
                'payment': p,
            })
        if p.delivery.status != 'Verified':
            issues.append({
                'title': 'Payment mismatch',
                'related': p.code,
                'desc': f"Payment {p.code} is linked to delivery {p.delivery.code}, which is not verified.",
                'payment': p,
            })

    # 4) Stock
    for s in Stock.objects.filter(status='Mismatch'):
        issues.append({
            'title': 'Stock mismatch',
            'related': s.produce,
            'desc': (f"More {s.produce} has been dispatched ({s.dispatched:g} kg) "
                     f"than has been received ({s.received:g} kg)."),
        })
    return issues


def _sync_statuses(issues):
    """Update the status badges of deliveries, payments and farmers to match the issues."""
    bad_deliveries = {i['delivery'].pk for i in issues if i.get('delivery') and i.get('blocking')}
    Delivery.objects.filter(pk__in=bad_deliveries).exclude(status='Error').update(status='Error')
    Delivery.objects.filter(status='Error').exclude(pk__in=bad_deliveries).update(status='Pending')

    bad_payments = {i['payment'].pk for i in issues if i.get('payment')}
    Payment.objects.filter(pk__in=bad_payments, status='Pending').update(status='Mismatch')
    Payment.objects.filter(status='Mismatch').exclude(pk__in=bad_payments).update(status='Pending')

    bad_farmers = {i['farmer'].pk for i in issues if i.get('farmer')}
    Farmer.objects.filter(pk__in=bad_farmers, status='Active').update(status='Review')


def run_checks():
    """
    Scan every record. New problems are added to the Errors page;
    problems that no longer exist are marked 'Corrected' automatically.
    Returns (new_count, resolved_count).
    """
    recalc_stock()
    _sync_statuses(collect_issues())
    recalc_stock()
    issues = collect_issues()

    current = {(i['title'], i['related']) for i in issues}
    open_errors = list(ErrorRecord.objects.exclude(status='Corrected'))
    existing = {(e.title, e.related_record) for e in open_errors}

    created = 0
    for i in issues:
        key = (i['title'], i['related'])
        if key not in existing:
            ErrorRecord.objects.create(title=i['title'], description=i['desc'], related_record=i['related'])
            existing.add(key)
            created += 1

    resolved = 0
    for e in open_errors:
        if (e.title, e.related_record) not in current:
            e.status = 'Corrected'
            e.save(update_fields=['status'])
            resolved += 1
    return created, resolved
