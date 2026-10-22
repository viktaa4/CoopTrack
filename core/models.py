from django.db import models
from django.contrib.auth.models import User

class Farmer(models.Model):
    STATUS_CHOICES = [
        ('Active', 'Active'),
        ('Review', 'Review'),
        ('Inactive', 'Inactive'),
    ]
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20)
    produce_type = models.CharField(max_length=50)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Active')
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def code(self):
        return f"F{self.pk:03d}"

    def __str__(self):
        return self.name


class Delivery(models.Model):
    STATUS_CHOICES = [
        ('Verified', 'Verified'),
        ('Pending', 'Pending'),
        ('Error', 'Error'),
    ]
    farmer = models.ForeignKey(Farmer, on_delete=models.CASCADE)
    produce = models.CharField(max_length=50)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    receipt_no = models.CharField(max_length=50)
    delivery_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def code(self):
        return f"DLV-{self.pk:03d}"

    def __str__(self):
        return f"{self.receipt_no} - {self.farmer.name}"


class Payment(models.Model):
    STATUS_CHOICES = [
        ('Paid', 'Paid'),
        ('Pending', 'Pending'),
        ('Mismatch', 'Mismatch'),
    ]
    farmer = models.ForeignKey(Farmer, on_delete=models.CASCADE)
    delivery = models.OneToOneField(Delivery, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    receipt_no = models.CharField(max_length=50)
    payment_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def code(self):
        return f"PAY-{self.pk:03d}"

    def __str__(self):
        return f"{self.receipt_no} - {self.amount}"


class Stock(models.Model):
    STATUS_CHOICES = [
        ('Verified', 'Verified'),
        ('Mismatch', 'Mismatch'),
    ]
    produce = models.CharField(max_length=50, unique=True)
    received = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    dispatched = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    available = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Verified')

    def __str__(self):
        return self.produce


class ErrorRecord(models.Model):
    STATUS_CHOICES = [
        ('Requires Correction', 'Requires Correction'),
        ('Under Review', 'Under Review'),
        ('Corrected', 'Corrected'),
    ]
    title = models.CharField(max_length=200)
    description = models.TextField()
    related_record = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='Requires Correction')
    detected_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    message = models.CharField(max_length=255)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.message


class ContactMessage(models.Model):
    """Messages sent from the Contact form on the landing page."""
    name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=30, blank=True)
    message = models.TextField()
    emailed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} - {self.created_at:%d %b %Y %H:%M}"
