# Bulletins

One folder per service (YYYY/MM/YYYY-MM-DD-<occasion>): the source-safe config,
the week's staged music images, and the finished PDFs. The renderer's temporary
staged config is not retained. `bulletin-log.json` is the approved record of
every service and answers questions like "when did we last sing this?".

If a review package needs a change, use `revise` with the exact prior
`bulletin-production-receipt.json`. The replacement is verified before the
prior unapproved package moves to `.revisions/<week>/<run-id>/`. Revisions keep
the predecessor receipt and artifacts recoverable, link both receipts, and are
idempotent. Approved packages remain in place and approved history is never
overwritten.
