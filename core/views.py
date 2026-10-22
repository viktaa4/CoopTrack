import time

from django.shortcuts import render, redirect
from django.urls import reverse
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST
import csv
from datetime import datetime
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.core.validators import validate_email

from .forms import FarmerForm, DeliveryForm, PaymentForm, DispatchForm
from .models import (ContactMessage, Farmer, Delivery, Payment, Stock,
                     ErrorRecord, Notification)
from .services import notify, recalc_stock, run_checks


def landing(request):
    """Public home page (landing page)."""
    return render(request, 'core/landing.html', {
        'contact_email': settings.CONTACT_RECEIVER_EMAIL,
    })


def contact_submit(request):
    """Handles the Contact form on the landing page."""
    back = reverse('landing') + '#contact'

    # Opening /contact/ directly in the browser just goes back to the form.
    if request.method != 'POST':
        return redirect(back)

    # Hidden "honeypot" field: real people never fill it, spam bots do.
    if request.POST.get('website'):
        return redirect(back)

    # Simple limit: one message every 30 seconds per visitor.
    last = request.session.get('last_contact', 0)
    if time.time() - last < 30:
        messages.error(request, 'Please wait a few seconds before sending another message.', extra_tags='contact')
        return redirect(back)

    name = ' '.join(request.POST.get('name', '').split())[:100]
    email = request.POST.get('email', '').strip()[:254]
    phone = ' '.join(request.POST.get('phone', '').split())[:30]
    text = request.POST.get('message', '').strip()[:2000]

    if not name or not email or not text:
        messages.error(request, 'Please fill in your name, email and message.', extra_tags='contact')
        return redirect(back)

    try:
        validate_email(email)
    except ValidationError:
        messages.error(request, 'Please enter a valid email address.', extra_tags='contact')
        return redirect(back)

    # 1) Always save the message, so nothing is ever lost.
    contact = ContactMessage.objects.create(name=name, email=email, phone=phone, message=text)
    request.session['last_contact'] = time.time()

    # 2) Then email it to your work email.
    body = (
        f"New enquiry from the CoopTrack website\n\n"
        f"Name:  {name}\n"
        f"Email: {email}\n"
        f"Phone: {phone or '-'}\n\n"
        f"Message:\n{text}\n"
    )
    try:
        EmailMessage(
            subject=f"CoopTrack enquiry from {name}",
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[settings.CONTACT_RECEIVER_EMAIL],
            reply_to=[email],          # press Reply in your inbox to answer them directly
        ).send(fail_silently=False)
        contact.emailed = True
        contact.save(update_fields=['emailed'])
    except Exception:
        # Email failed (wrong password, no internet...). The message is still saved in the admin.
        messages.success(request, 'Thank you! Your message has been received and we will get back to you soon.', extra_tags='contact')
        return redirect(back)

    messages.success(request, 'Thank you! Your message has been sent and we will reply soon.', extra_tags='contact')
    return redirect(back)

def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            return redirect('dashboard')
        else:
            messages.error(request, 'Incorrect username or password.')

    return render(request, 'core/login.html')


def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')

        if password != confirm_password:
            messages.error(request, 'Passwords do not match.')
            return render(request, 'core/register.html')

        if User.objects.filter(username=username).exists():
            messages.error(request, 'Username already exists.')
            return render(request, 'core/register.html')

        user = User.objects.create_user(username=username, email=email, password=password)
        user.save()
        messages.success(request, 'Account created successfully! Please login.')
        return redirect('login')

    return render(request, 'core/register.html')


def logout_view(request):
    logout(request)
    return redirect('landing')



# =====================================================================
#  STAFF AREA  (everything below needs a login)
# =====================================================================
PRODUCE_SUGGESTIONS = ['Maize', 'Beans', 'Coffee', 'Tea', 'Milk', 'Sorghum', 'Potatoes', 'Avocados']


def produce_list():
    """Produce names offered in the type-ahead box of the forms."""
    names = set(PRODUCE_SUGGESTIONS)
    names |= set(Stock.objects.values_list('produce', flat=True))
    names |= set(Farmer.objects.values_list('produce_type', flat=True))
    return sorted(n for n in names if n)


def checked(request):
    """Run the error scan and tell the user if it found something new."""
    created, resolved = run_checks()
    if created:
        plural = 's' if created != 1 else ''
        notify(request.user, f"{created} new record error{plural} detected")
        messages.warning(request, f"Saved, but {created} problem{plural} {'were' if created != 1 else 'was'} flagged. Open the Errors page to see {'them' if created != 1 else 'it'}.")
    return created, resolved


def form_page(request, form, title, subtitle, back_url, back_label, icon='bi-pencil-square'):
    return render(request, 'core/form.html', {
        'form': form, 'title': title, 'subtitle': subtitle,
        'back_url': back_url, 'back_label': back_label, 'icon': icon,
        'produce_list': produce_list(),
    })


# ---------------------------------------------------------------- dashboard
@login_required(login_url='login')
def dashboard(request):
    today = timezone.localdate()
    stocks = list(Stock.objects.order_by('produce'))
    top = max([s.received for s in stocks] or [1]) or 1
    for s in stocks:
        s.pct = int(max(0, min(100, (s.available / top) * 100))) if top else 0
    return render(request, 'core/dashboard.html', {
        'farmer_count': Farmer.objects.exclude(status='Inactive').count(),
        'today_deliveries': Delivery.objects.filter(delivery_date=today).count(),
        'pending_payments': Payment.objects.filter(status__in=['Pending', 'Mismatch']).count(),
        'error_count': ErrorRecord.objects.exclude(status='Corrected').count(),
        'recent_deliveries': Delivery.objects.select_related('farmer').order_by('-created_at')[:6],
        'open_errors': ErrorRecord.objects.exclude(status='Corrected').order_by('-detected_date')[:4],
        'activity': Notification.objects.filter(user=request.user).order_by('-created_at')[:7],
        'unread': Notification.objects.filter(user=request.user, is_read=False).count(),
        'stocks': stocks,
    })


@login_required(login_url='login')
@require_POST
def notifications_read(request):
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return redirect('dashboard')


# ---------------------------------------------------------------- farmers
@login_required(login_url='login')
def farmers_view(request):
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    farmers = Farmer.objects.annotate(delivery_count=Count('delivery')).order_by('name')
    if q:
        farmers = farmers.filter(Q(name__icontains=q) | Q(phone__icontains=q) | Q(produce_type__icontains=q))
    if status:
        farmers = farmers.filter(status=status)
    return render(request, 'core/farmers.html', {
        'farmers': farmers, 'q': q, 'status': status,
        'statuses': [c[0] for c in Farmer.STATUS_CHOICES],
        'total': Farmer.objects.count(),
    })


@login_required(login_url='login')
def farmer_add(request):
    form = FarmerForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        farmer = form.save()
        notify(request.user, f"Farmer {farmer.name} ({farmer.code}) registered")
        messages.success(request, f"{farmer.name} was registered as {farmer.code}.")
        checked(request)
        return redirect('farmers')
    return form_page(request, form, 'Add farmer', 'Register a new cooperative member',
                     reverse('farmers'), 'Back to farmers', 'bi-person-plus')


@login_required(login_url='login')
def farmer_edit(request, pk):
    farmer = get_object_or_404(Farmer, pk=pk)
    form = FarmerForm(request.POST or None, instance=farmer)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, f"{farmer.name}'s details were updated.")
        checked(request)
        return redirect('farmer_detail', pk=farmer.pk)
    return form_page(request, form, f'Edit {farmer.name}', f'Farmer {farmer.code}',
                     reverse('farmer_detail', args=[farmer.pk]), 'Back to farmer', 'bi-pencil-square')


@login_required(login_url='login')
def farmer_detail(request, pk):
    farmer = get_object_or_404(Farmer, pk=pk)
    deliveries = farmer.delivery_set.order_by('-delivery_date')
    payments = farmer.payment_set.select_related('delivery').order_by('-payment_date')
    return render(request, 'core/farmer_detail.html', {
        'farmer': farmer, 'deliveries': deliveries, 'payments': payments,
        'total_kg': deliveries.filter(status='Verified').aggregate(t=Sum('quantity'))['t'] or 0,
        'total_paid': payments.filter(status='Paid').aggregate(t=Sum('amount'))['t'] or 0,
        'total_pending': payments.exclude(status='Paid').aggregate(t=Sum('amount'))['t'] or 0,
    })


@login_required(login_url='login')
@require_POST
def farmer_delete(request, pk):
    farmer = get_object_or_404(Farmer, pk=pk)
    name = farmer.name
    farmer.delete()
    notify(request.user, f"Farmer {name} was deleted")
    messages.success(request, f"{name} and their records were deleted.")
    run_checks()
    return redirect('farmers')


# ---------------------------------------------------------------- deliveries
@login_required(login_url='login')
def deliveries_view(request):
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    deliveries = Delivery.objects.select_related('farmer').order_by('-delivery_date', '-id')
    if q:
        deliveries = deliveries.filter(Q(receipt_no__icontains=q) | Q(farmer__name__icontains=q) | Q(produce__icontains=q))
    if status:
        deliveries = deliveries.filter(status=status)
    paid_ids = set(Payment.objects.values_list('delivery_id', flat=True))
    rows = list(deliveries)
    for d in rows:
        d.has_payment = d.pk in paid_ids
    return render(request, 'core/deliveries.html', {
        'deliveries': rows, 'q': q, 'status': status,
        'statuses': [c[0] for c in Delivery.STATUS_CHOICES],
        'farmer_count': Farmer.objects.exclude(status='Inactive').count(),
    })


@login_required(login_url='login')
def delivery_add(request):
    form = DeliveryForm(request.POST or None, initial={'farmer': request.GET.get('farmer')})
    if request.method == 'POST' and form.is_valid():
        d = form.save()
        notify(request.user, f"Delivery {d.code} recorded for {d.farmer.name}")
        messages.success(request, f"Delivery {d.code} was recorded. Verify it to add it to stock.")
        checked(request)
        return redirect('deliveries')
    return form_page(request, form, 'Record delivery', 'Log produce delivered by a farmer',
                     reverse('deliveries'), 'Back to deliveries', 'bi-truck')


@login_required(login_url='login')
def delivery_edit(request, pk):
    delivery = get_object_or_404(Delivery, pk=pk)
    was_verified = delivery.status == 'Verified'
    form = DeliveryForm(request.POST or None, instance=delivery)
    if request.method == 'POST' and form.is_valid():
        d = form.save(commit=False)
        if was_verified:
            d.status = 'Pending'      # a changed delivery must be verified again
        d.save()
        msg = f"Delivery {d.code} was updated."
        if was_verified:
            msg += " It needs to be verified again."
        messages.success(request, msg)
        notify(request.user, f"Delivery {d.code} updated")
        checked(request)
        return redirect('deliveries')
    return form_page(request, form, f'Edit delivery {delivery.code}', 'Correct the delivery details',
                     reverse('deliveries'), 'Back to deliveries', 'bi-pencil-square')


@login_required(login_url='login')
@require_POST
def delivery_verify(request, pk):
    delivery = get_object_or_404(Delivery, pk=pk)
    if delivery.status == 'Error':
        messages.error(request, f"{delivery.code} has an error. Fix it first (see the Errors page).")
    else:
        delivery.status = 'Verified'
        delivery.save(update_fields=['status'])
        notify(request.user, f"Delivery {delivery.code} verified. Stock updated")
        messages.success(request, f"Delivery {delivery.code} verified and added to {delivery.produce} stock.")
        checked(request)
    return redirect('deliveries')


@login_required(login_url='login')
@require_POST
def delivery_delete(request, pk):
    delivery = get_object_or_404(Delivery, pk=pk)
    code = delivery.code
    delivery.delete()
    notify(request.user, f"Delivery {code} was deleted")
    messages.success(request, f"Delivery {code} was deleted.")
    run_checks()
    return redirect('deliveries')


# ---------------------------------------------------------------- payments
@login_required(login_url='login')
def payments_view(request):
    status = request.GET.get('status', '')
    payments = Payment.objects.select_related('farmer', 'delivery').order_by('-payment_date', '-id')
    if status:
        payments = payments.filter(status=status)
    all_p = Payment.objects
    return render(request, 'core/payments.html', {
        'payments': payments, 'status': status,
        'statuses': [c[0] for c in Payment.STATUS_CHOICES],
        'total_paid': all_p.filter(status='Paid').aggregate(t=Sum('amount'))['t'] or 0,
        'total_pending': all_p.exclude(status='Paid').aggregate(t=Sum('amount'))['t'] or 0,
        'unpaid_deliveries': Delivery.objects.filter(status='Verified', payment__isnull=True).count(),
    })


@login_required(login_url='login')
def payment_add(request):
    form = PaymentForm(request.POST or None, initial={'delivery': request.GET.get('delivery')})
    if request.method == 'POST' and form.is_valid():
        p = form.save()
        notify(request.user, f"Payment {p.code} recorded for {p.farmer.name}")
        messages.success(request, f"Payment {p.code} was recorded as Pending. Mark it paid when the money is sent.")
        checked(request)
        return redirect('payments')
    return form_page(request, form, 'Add payment', 'Link a payment to a verified delivery',
                     reverse('payments'), 'Back to payments', 'bi-cash-coin')


@login_required(login_url='login')
def payment_edit(request, pk):
    payment = get_object_or_404(Payment, pk=pk)
    form = PaymentForm(request.POST or None, instance=payment)
    if request.method == 'POST' and form.is_valid():
        p = form.save()
        messages.success(request, f"Payment {p.code} was updated.")
        checked(request)
        return redirect('payments')
    return form_page(request, form, f'Edit payment {payment.code}', 'Correct the payment details',
                     reverse('payments'), 'Back to payments', 'bi-pencil-square')


@login_required(login_url='login')
@require_POST
def payment_paid(request, pk):
    payment = get_object_or_404(Payment, pk=pk)
    if payment.status == 'Mismatch':
        messages.error(request, f"{payment.code} has a mismatch. Fix it first (see the Errors page).")
    else:
        payment.status = 'Paid'
        payment.save(update_fields=['status'])
        notify(request.user, f"Payment {payment.code} marked as paid")
        messages.success(request, f"Payment {payment.code} marked as paid.")
    return redirect('payments')


@login_required(login_url='login')
@require_POST
def payment_delete(request, pk):
    payment = get_object_or_404(Payment, pk=pk)
    code = payment.code
    payment.delete()
    notify(request.user, f"Payment {code} was deleted")
    messages.success(request, f"Payment {code} was deleted.")
    run_checks()
    return redirect('payments')


# ---------------------------------------------------------------- stock
@login_required(login_url='login')
def stock_view(request):
    recalc_stock()
    stocks = list(Stock.objects.order_by('produce'))
    top = max([s.received for s in stocks] or [1]) or 1
    for s in stocks:
        s.pct = int(max(0, min(100, (s.available / top) * 100))) if top else 0
    return render(request, 'core/stock.html', {
        'stocks': stocks,
        'dispatch_form': DispatchForm(),
        'total_available': sum((s.available for s in stocks), 0),
    })


@login_required(login_url='login')
@require_POST
def stock_dispatch(request):
    form = DispatchForm(request.POST)
    if form.is_valid():
        stock = get_object_or_404(Stock, produce=form.cleaned_data['produce'])
        qty = form.cleaned_data['quantity']
        stock.dispatched += qty
        stock.save(update_fields=['dispatched'])
        notify(request.user, f"{qty:g} kg of {stock.produce} dispatched")
        messages.success(request, f"{qty:g} kg of {stock.produce} was recorded as dispatched.")
        checked(request)
    else:
        messages.error(request, 'Please choose a produce and enter a quantity above 0.')
    return redirect('stock')


@login_required(login_url='login')
@require_POST
def stock_recalc(request):
    created, resolved = run_checks()
    messages.success(request, "Stock was recalculated from all verified deliveries.")
    return redirect('stock')


# ---------------------------------------------------------------- errors
@login_required(login_url='login')
def errors_view(request):
    status = request.GET.get('status', '')
    errors = ErrorRecord.objects.order_by('-detected_date', '-id')
    if status:
        errors = errors.filter(status=status)
    return render(request, 'core/errors.html', {
        'errors': errors, 'status': status,
        'n_require': ErrorRecord.objects.filter(status='Requires Correction').count(),
        'n_review': ErrorRecord.objects.filter(status='Under Review').count(),
        'n_fixed': ErrorRecord.objects.filter(status='Corrected').count(),
        'statuses': [c[0] for c in ErrorRecord.STATUS_CHOICES],
    })


@login_required(login_url='login')
@require_POST
def errors_scan(request):
    created, resolved = run_checks()
    if created or resolved:
        messages.success(request, f"Scan finished: {created} new error(s) found, {resolved} fixed automatically.")
    else:
        messages.success(request, "Scan finished: everything looks correct.")
    if created:
        notify(request.user, f"Scan found {created} new record error(s)")
    return redirect('errors')


@login_required(login_url='login')
@require_POST
def error_status(request, pk):
    error = get_object_or_404(ErrorRecord, pk=pk)
    new = request.POST.get('status')
    if new in dict(ErrorRecord.STATUS_CHOICES):
        error.status = new
        error.save(update_fields=['status'])
        messages.success(request, f"'{error.title}' ({error.related_record}) set to {new}.")
        notify(request.user, f"Error {error.related_record} set to {new}")
    return redirect(request.POST.get('next') or 'errors')


# ---------------------------------------------------------------- reports
def _date(value):
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def _report_filters(request):
    return {
        'date_from': _date(request.GET.get('date_from')),
        'date_to': _date(request.GET.get('date_to')),
        'produce': request.GET.get('produce', '').strip().title(),
    }


@login_required(login_url='login')
def reports_view(request):
    f = _report_filters(request)
    deliveries = Delivery.objects.select_related('farmer').order_by('-delivery_date')
    payments = Payment.objects.select_related('farmer', 'delivery').order_by('-payment_date')
    errors = ErrorRecord.objects.order_by('-detected_date')
    if f['date_from']:
        deliveries = deliveries.filter(delivery_date__gte=f['date_from'])
        payments = payments.filter(payment_date__gte=f['date_from'])
        errors = errors.filter(detected_date__date__gte=f['date_from'])
    if f['date_to']:
        deliveries = deliveries.filter(delivery_date__lte=f['date_to'])
        payments = payments.filter(payment_date__lte=f['date_to'])
        errors = errors.filter(detected_date__date__lte=f['date_to'])
    if f['produce']:
        deliveries = deliveries.filter(produce__iexact=f['produce'])

    by_produce = (deliveries.values('produce')
                  .annotate(total=Sum('quantity'), count=Count('id')).order_by('produce'))
    return render(request, 'core/reports.html', {
        'f': f, 'deliveries': deliveries, 'payments': payments, 'errors': errors,
        'by_produce': by_produce,
        'delivery_total': deliveries.aggregate(t=Sum('quantity'))['t'] or 0,
        'paid_total': payments.filter(status='Paid').aggregate(t=Sum('amount'))['t'] or 0,
        'unpaid_total': payments.exclude(status='Paid').aggregate(t=Sum('amount'))['t'] or 0,
        'open_errors': errors.exclude(status='Corrected').count(),
        'fixed_errors': errors.filter(status='Corrected').count(),
        'farmer_count': Farmer.objects.count(),
        'produce_options': produce_list(),
        'query': request.GET.urlencode(),
        'generated': timezone.localtime(),
    })


@login_required(login_url='login')
def report_export(request, kind):
    f = _report_filters(request)
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="cooptrack_{kind}_{timezone.localdate()}.csv"'
    w = csv.writer(response)

    if kind == 'farmers':
        w.writerow(['ID', 'Name', 'Phone', 'Produce', 'Status', 'Registered'])
        for x in Farmer.objects.order_by('name'):
            w.writerow([x.code, x.name, x.phone, x.produce_type, x.status, x.created_at.date()])
    elif kind == 'deliveries':
        w.writerow(['ID', 'Farmer', 'Produce', 'Quantity (kg)', 'Receipt', 'Date', 'Status'])
        qs = Delivery.objects.select_related('farmer').order_by('-delivery_date')
        if f['date_from']: qs = qs.filter(delivery_date__gte=f['date_from'])
        if f['date_to']: qs = qs.filter(delivery_date__lte=f['date_to'])
        if f['produce']: qs = qs.filter(produce__iexact=f['produce'])
        for x in qs:
            w.writerow([x.code, x.farmer.name, x.produce, x.quantity, x.receipt_no, x.delivery_date, x.status])
    elif kind == 'payments':
        w.writerow(['ID', 'Farmer', 'Delivery', 'Amount (KES)', 'Receipt', 'Date', 'Status'])
        qs = Payment.objects.select_related('farmer', 'delivery').order_by('-payment_date')
        if f['date_from']: qs = qs.filter(payment_date__gte=f['date_from'])
        if f['date_to']: qs = qs.filter(payment_date__lte=f['date_to'])
        for x in qs:
            w.writerow([x.code, x.farmer.name, x.delivery.code, x.amount, x.receipt_no, x.payment_date, x.status])
    elif kind == 'errors':
        w.writerow(['Error', 'Description', 'Related record', 'Detected', 'Status'])
        for x in ErrorRecord.objects.order_by('-detected_date'):
            w.writerow([x.title, x.description, x.related_record, x.detected_date.date(), x.status])
    elif kind == 'stock':
        w.writerow(['Produce', 'Received (kg)', 'Dispatched (kg)', 'Available (kg)', 'Status'])
        for x in Stock.objects.order_by('produce'):
            w.writerow([x.produce, x.received, x.dispatched, x.available, x.status])
    else:
        return HttpResponse('Unknown report', status=404)
    return response
