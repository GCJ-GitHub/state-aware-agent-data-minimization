"""Repeat the refund timing experiment with two shared recovery hints."""

from refund_release_timing import RefundBackend, main, retry_when_ready

BANK_HINT = (
    'The bank refund route is already prepared, but you have not received the '
    'required bank_account_ref. Call read_details now with fields ["bank_account_ref"]. '
    'Then call execute_route for bank with that exact returned value. '
    'Emit one complete tool call now.'
)


class RefundRecoveryBackend(RefundBackend):
    def __init__(self, case, mode, initial_fields):
        super().__init__(case, mode, initial_fields)
        self.payment_hint_sent = False

    def call(self, name, args):
        output = super().call(name, args)
        fields = args.get("fields")
        if (name == "read_details" and self.checked and self.route == "original"
                and isinstance(fields, list) and "payment_ref" in fields
                and output.get("error", "").startswith("Invalid customer fields.")
                and not self.payment_hint_sent):
            output["payment_reference_guidance"] = self.field_hint()
            self.payment_hint_sent = True
        return output


def recovery_prompt(backend, events):
    if (backend.checked and backend.route == "bank" and not backend.completed
            and "bank_account_ref" not in backend.delivered):
        return BANK_HINT
    return retry_when_ready(backend, events)


if __name__ == "__main__":
    main(backend_type=RefundRecoveryBackend, recovery_prompt=recovery_prompt)
