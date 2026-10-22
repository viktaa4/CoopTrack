"""
Fill CoopTrack with realistic sample data (useful for screenshots and demos).

    python manage.py seed_demo            add sample data
    python manage.py seed_demo --clear    delete ALL farmers/deliveries/payments/stock/errors first
"""
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Farmer, Delivery, Payment, Stock, ErrorRecord, Notification
from core.services import run_checks


class Command(BaseCommand):
    help = "Create sample farmers, deliveries, payments and stock."

    def add_arguments(self, parser):
        parser.add_argument('--clear', action='store_true', help='Delete existing records first')

    def handle(self, *args, **options):
        if options['clear']:
            for model in (ErrorRecord, Notification, Payment, Delivery, Stock, Farmer):
                model.objects.all().delete()
            self.stdout.write('Old records deleted.')

        today = timezone.localdate()
        day = lambda n: today - timedelta(days=n)

        people = [
            ('Peter Mwangi', '0712345678', 'Maize'),
            ('Mary Wanjiku', '0722456789', 'Beans'),
            ('John Kamau', '0733567890', 'Maize'),
            ('Grace Njeri', '0745678901', 'Coffee'),
            ('Samuel Kiprono', '0710112233', 'Maize'),
            ('Faith Chebet', '0723344556', 'Milk'),
            ('Joseph Otieno', '0701234567', 'Beans'),
            ('Agnes Wambui', '07123', 'Tea'),            # deliberately wrong phone -> shows an error
        ]
        farmers = []
        for name, phone, produce in people:
            f, _ = Farmer.objects.get_or_create(name=name, defaults={'phone': phone, 'produce_type': produce})
            farmers.append(f)

        # (farmer index, produce, kg, receipt, days ago, verify?)
        deliveries = [
            (0, 'Maize', 250, 'R-1001', 6, True),
            (1, 'Beans', 180, 'R-1002', 5, True),
            (2, 'Maize', 320, 'R-1003', 5, True),
            (3, 'Coffee', 90, 'R-1004', 4, True),
            (4, 'Maize', 410, 'R-1005', 3, True),
            (5, 'Milk', 150, 'R-1006', 2, True),
            (6, 'Beans', 120, 'R-1007', 1, True),
            (0, 'Maize', 275, 'R-1008', 0, False),
            (1, 'Beans', 95, 'R-1008', 0, False),         # same receipt as the line above -> error
        ]
        made = []
        for fi, produce, kg, receipt, ago, verify in deliveries:
            d, created = Delivery.objects.get_or_create(
                farmer=farmers[fi], produce=produce, receipt_no=receipt,
                defaults={'quantity': Decimal(kg), 'delivery_date': day(ago),
                          'status': 'Verified' if verify else 'Pending'})
            if created and ago > 0 and receipt != 'R-1002':
                # pretend it was recorded on the day it happened (R-1002 is deliberately recorded late)
                when = timezone.make_aware(datetime.combine(d.delivery_date, time(15, 0)))
                Delivery.objects.filter(pk=d.pk).update(created_at=when)
            made.append(d)

        # payments for the first verified deliveries
        pay = [(0, 18500, 'R-1001', 'Paid'), (1, 21600, 'R-1002', 'Paid'),
               (2, 24000, 'R-1003', 'Pending'),
               (3, 31500, 'R-1044', 'Pending')]            # wrong receipt -> mismatch error
        for di, amount, receipt, status in pay:
            d = made[di]
            Payment.objects.get_or_create(
                delivery=d, defaults={'farmer': d.farmer, 'amount': Decimal(amount), 'receipt_no': receipt,
                                      'payment_date': d.delivery_date + timedelta(days=1), 'status': status})

        run_checks()
        # a dispatch so the stock page shows movement
        for produce, kg in (('Maize', 300), ('Beans', 100)):
            s = Stock.objects.filter(produce=produce).first()
            if s and s.dispatched == 0:
                s.dispatched = Decimal(kg)
                s.save(update_fields=['dispatched'])
        run_checks()

        self.stdout.write(self.style.SUCCESS(
            f"Done: {Farmer.objects.count()} farmers, {Delivery.objects.count()} deliveries, "
            f"{Payment.objects.count()} payments, {Stock.objects.count()} stock rows, "
            f"{ErrorRecord.objects.exclude(status='Corrected').count()} open errors."))
