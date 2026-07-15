"""Invoice pricing exercise with intentionally incomplete validation and rounding."""


def calculate_invoice(lines, discount_bps=0, tax_bps=0):
    subtotal = sum(float(line["unit_price"]) * line["quantity"] for line in lines)
    discount = subtotal * discount_bps / 10_000
    tax = (subtotal - discount) * tax_bps / 10_000
    total = subtotal - discount + tax
    return {
        "subtotal": f"{subtotal:.2f}",
        "discount": f"{discount:.2f}",
        "tax": f"{tax:.2f}",
        "total": f"{total:.2f}",
    }
