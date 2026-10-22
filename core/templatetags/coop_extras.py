from django import template

register = template.Library()

BADGES = {
    # deliveries / stock
    'Verified': 'b-green', 'Pending': 'b-amber', 'Error': 'b-red', 'Mismatch': 'b-red',
    # payments
    'Paid': 'b-green',
    # farmers
    'Active': 'b-green', 'Review': 'b-amber', 'Inactive': 'b-grey',
    # errors
    'Requires Correction': 'b-red', 'Under Review': 'b-amber', 'Corrected': 'b-green',
}


@register.filter
def badge(status):
    """Colour class for a status badge, e.g. {{ d.status|badge }}"""
    return BADGES.get(status, 'b-grey')
