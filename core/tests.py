from decimal import Decimal
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Farmer, Delivery, Payment, Stock, ErrorRecord
from .services import run_checks, phone_is_valid


class CoopTrackTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('staff', password='pass12345')
        self.client.login(username='staff', password='pass12345')
        self.farmer = Farmer.objects.create(name='Peter Mwangi', phone='0712345678', produce_type='Maize')
        self.today = timezone.localdate()

    def delivery(self, receipt='R-1', qty=100, status='Pending', produce='Maize'):
        return Delivery.objects.create(farmer=self.farmer, produce=produce, quantity=Decimal(qty),
                                       receipt_no=receipt, delivery_date=self.today, status=status)

    # ---- access
    def test_pages_need_login(self):
        self.client.logout()
        for name in ['dashboard', 'farmers', 'deliveries', 'payments', 'stock', 'errors', 'reports']:
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 302, name)
            self.assertIn('/login/', r['Location'])

    def test_all_pages_open_when_logged_in(self):
        for name in ['dashboard', 'farmers', 'deliveries', 'payments', 'stock', 'errors', 'reports',
                     'farmer_add', 'delivery_add', 'payment_add']:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    # ---- farmers
    def test_add_farmer(self):
        r = self.client.post(reverse('farmer_add'), {'name': 'Mary Wanjiku', 'phone': '0722 456 789',
                                                      'produce_type': 'beans', 'status': 'Active'})
        self.assertRedirects(r, reverse('farmers'))
        f = Farmer.objects.get(name='Mary Wanjiku')
        self.assertEqual(f.phone, '0722456789')
        self.assertEqual(f.produce_type, 'Beans')

    def test_farmer_phone_validation(self):
        r = self.client.post(reverse('farmer_add'), {'name': 'X', 'phone': '12', 'produce_type': 'Maize', 'status': 'Active'})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Farmer.objects.filter(name='X').exists())

    def test_search_farmers(self):
        r = self.client.get(reverse('farmers') + '?q=peter')
        self.assertContains(r, 'Peter Mwangi')
        r = self.client.get(reverse('farmers') + '?q=nobody')
        self.assertNotContains(r, 'Peter Mwangi')

    def test_delete_farmer(self):
        self.client.post(reverse('farmer_delete', args=[self.farmer.pk]))
        self.assertFalse(Farmer.objects.exists())

    # ---- deliveries and stock
    def test_verify_delivery_updates_stock(self):
        d = self.delivery(qty=250)
        self.client.post(reverse('delivery_verify', args=[d.pk]))
        d.refresh_from_db()
        self.assertEqual(d.status, 'Verified')
        s = Stock.objects.get(produce='Maize')
        self.assertEqual(s.received, Decimal('250'))
        self.assertEqual(s.available, Decimal('250'))

    def test_pending_delivery_not_counted_in_stock(self):
        self.delivery(qty=500)
        run_checks()
        self.assertEqual(Stock.objects.get(produce='Maize').received, 0)

    def test_dispatch_reduces_available(self):
        d = self.delivery(qty=300, status='Verified')
        run_checks()
        self.client.post(reverse('stock_dispatch'), {'produce': 'Maize', 'quantity': '120'})
        s = Stock.objects.get(produce='Maize')
        self.assertEqual(s.available, Decimal('180'))
        self.assertEqual(s.status, 'Verified')

    def test_over_dispatch_flags_stock_mismatch(self):
        self.delivery(qty=100, status='Verified')
        run_checks()
        self.client.post(reverse('stock_dispatch'), {'produce': 'Maize', 'quantity': '150'})
        self.assertEqual(Stock.objects.get(produce='Maize').status, 'Mismatch')
        self.assertTrue(ErrorRecord.objects.filter(title='Stock mismatch', status='Requires Correction').exists())

    # ---- error detection
    def test_duplicate_receipt_flagged_and_auto_resolved(self):
        a = self.delivery(receipt='R-9')
        b = self.delivery(receipt='R-9')
        run_checks()
        self.assertEqual(ErrorRecord.objects.filter(title='Receipt mismatch').exclude(status='Corrected').count(), 2)
        a.refresh_from_db()
        self.assertEqual(a.status, 'Error')
        # cannot verify a delivery that has an error
        self.client.post(reverse('delivery_verify', args=[a.pk]))
        a.refresh_from_db()
        self.assertEqual(a.status, 'Error')
        # fix the duplicate -> the errors clear by themselves
        b.receipt_no = 'R-10'
        b.save()
        run_checks()
        self.assertEqual(ErrorRecord.objects.exclude(status='Corrected').count(), 0)
        a.refresh_from_db()
        self.assertEqual(a.status, 'Pending')

    def test_bad_phone_flagged(self):
        Farmer.objects.create(name='Agnes', phone='07123', produce_type='Tea')
        run_checks()
        self.assertTrue(ErrorRecord.objects.filter(title='Wrong farmer information').exists())

    def test_late_record_flagged(self):
        d = self.delivery()
        Delivery.objects.filter(pk=d.pk).update(delivery_date=self.today - timedelta(days=4))
        run_checks()
        self.assertTrue(ErrorRecord.objects.filter(title='Late delivery record').exists())

    # ---- payments
    def test_payment_only_for_verified_delivery(self):
        d = self.delivery(status='Pending')
        r = self.client.post(reverse('payment_add'), {'delivery': d.pk, 'amount': '1000',
                                                       'receipt_no': 'R-1', 'payment_date': self.today})
        self.assertEqual(r.status_code, 200)       # form re-shown with an error
        self.assertFalse(Payment.objects.exists())

    def test_payment_receipt_mismatch_flagged(self):
        d = self.delivery(receipt='R-5', status='Verified')
        self.client.post(reverse('payment_add'), {'delivery': d.pk, 'amount': '18500',
                                                   'receipt_no': 'R-999', 'payment_date': self.today})
        p = Payment.objects.get()
        self.assertEqual(p.farmer, self.farmer)
        self.assertEqual(p.status, 'Mismatch')
        # cannot mark a mismatched payment as paid
        self.client.post(reverse('payment_paid', args=[p.pk]))
        p.refresh_from_db()
        self.assertEqual(p.status, 'Mismatch')

    def test_payment_marked_paid(self):
        d = self.delivery(receipt='R-6', status='Verified')
        self.client.post(reverse('payment_add'), {'delivery': d.pk, 'amount': '5000',
                                                   'receipt_no': 'r-6', 'payment_date': self.today})
        p = Payment.objects.get()
        self.assertEqual(p.status, 'Pending')
        self.client.post(reverse('payment_paid', args=[p.pk]))
        p.refresh_from_db()
        self.assertEqual(p.status, 'Paid')

    # ---- errors page and reports
    def test_change_error_status(self):
        e = ErrorRecord.objects.create(title='Test', description='x', related_record='DLV-001')
        self.client.post(reverse('error_status', args=[e.pk]), {'status': 'Under Review'})
        e.refresh_from_db()
        self.assertEqual(e.status, 'Under Review')

    def test_dashboard_numbers(self):
        self.delivery()
        r = self.client.get(reverse('dashboard'))
        self.assertEqual(r.context['farmer_count'], 1)
        self.assertEqual(r.context['today_deliveries'], 1)

    def test_csv_exports(self):
        self.delivery(status='Verified')
        run_checks()
        for kind in ['farmers', 'deliveries', 'payments', 'errors', 'stock']:
            r = self.client.get(reverse('report_export', args=[kind]))
            self.assertEqual(r.status_code, 200, kind)
            self.assertEqual(r['Content-Type'], 'text/csv')
        self.assertContains(self.client.get(reverse('report_export', args=['farmers'])), 'Peter Mwangi')

    def test_phone_validator(self):
        for good in ['0712345678', '+254712345678', '254712345678', '0112345678']:
            self.assertTrue(phone_is_valid(good), good)
        for bad in ['07123', '0912345678', 'abc', '']:
            self.assertFalse(phone_is_valid(bad), bad)

    def test_contact_form_still_works(self):
        self.client.logout()
        r = self.client.post(reverse('contact_submit'), {'name': 'Jane', 'email': 'jane@example.com', 'message': 'Hi'})
        self.assertEqual(r.status_code, 302)
