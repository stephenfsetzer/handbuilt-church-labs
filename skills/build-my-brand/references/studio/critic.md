# Critic

The critic checks work before the pastor sees it. It runs in fresh context,
as its own worker, and it never made the piece it judges. A maker that judges
its own work forgives it; a critic with no memory of making it does not.

Start the worker prompt with "Work ALONE. Never spawn agents." and give it
only these inputs:

- screenshots of the piece at 1440 and 375 wide (never the code)
- the art direction and, for a page, its score
- the previous three sections or pieces it sits beside
- the [misses log](../taste/misses.md)

Never give it an earlier critique of the same piece.

## The questions, in order

1. Does it break a "never," or skip a decision rule?
2. Does it do what the score said: the right lead, ground, scale and layout?
3. Put it beside the last three. Does it blend in? If it does, the layout
   changes, not just the colors.
4. Could this be any church's website? Name what makes it this church.
5. Is anything clipped, crowded, closer than 24 px to an edge, or hard to
   read at phone width?
6. Does any photo appear somewhere else already? Near-duplicates count.

## The verdict

`pass`, or `redirect` with a reason and what to try instead. A redirect names
what the piece optimized for instead of the direction. Nothing reaches the
pastor without a pass, and every verdict is recorded with the workflow's
critique operation so the record shows what was set aside and why.

When a pastor overrules a pass, add the miss to the log as a note. It becomes
a rule only when it happens again or the person who owns the product confirms
it. One reaction is taste, not yet a rule.
