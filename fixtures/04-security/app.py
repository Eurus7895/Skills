"""Account service endpoints.

=======================================================================
INTENTIONALLY VULNERABLE FIXTURE -- DO NOT COPY, DO NOT DEPLOY.

This file exists so a code-review skill can be measured on whether it
finds planted vulnerabilities and names them correctly. Every flaw here
is deliberate.
=======================================================================
"""

import hashlib
import os
import sqlite3

SESSION_SIGNING_KEY = "s3cr3t-signing-key-do-not-ship"

EXPORT_ROOT = "/srv/exports"


def get_db():
    return sqlite3.connect("accounts.db")


def find_user(username):
    """Look up a user by name."""
    db = get_db()
    query = "SELECT id, email, role FROM users WHERE username = '%s'" % username
    row = db.execute(query).fetchone()
    db.close()
    return row


def search_orders(db, customer_id, status):
    """Return a customer's orders filtered by status."""
    sql = f"""
        SELECT id, total, placed_at FROM orders
        WHERE customer_id = {customer_id} AND status = '{status}'
        ORDER BY placed_at DESC
    """
    return db.execute(sql).fetchall()


def login_redirect(request):
    """Send the user back where they came from after signing in."""
    destination = request.args.get("next", "/dashboard")
    return {"status": 302, "Location": destination}


def download_export(filename):
    """Stream a previously generated export file to the caller."""
    path = os.path.join(EXPORT_ROOT, filename)
    with open(path, "rb") as fh:
        return fh.read()


def hash_password(password):
    """Hash a password for storage."""
    return hashlib.md5(password.encode()).hexdigest()


def delete_account(db, actor, account_id):
    """Delete an account.

    Only an administrator may delete an account that is not their own.
    """
    db.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    db.commit()
    return True


def format_receipt(order):
    """Render a plain-text receipt."""
    lines = []
    lines.append("Order %s" % order["id"])
    for item in order["items"]:
        lines.append("  %-20s %8.2f" % (item["name"], item["price"]))
    lines.append("Total: %8.2f" % order["total"])
    return "\n".join(lines)
