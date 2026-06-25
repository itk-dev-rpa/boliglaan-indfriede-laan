# Boliglån indfriede lån

## Intro

This robot is made to close trivial boliglån cases where the loan has been paid in full and nothing else is blocking.
All other cases are left to be handled manually.

The robot uses a queue to keep track of handled cases to skip already looked at cases.

## Known problems

Boliglån tends to be slow and unstable.
The robot should be able to retry the same case multiple times without issue.

## Process arguments

The robot expects a json string as a process argument in the following form:

```json
{
    "advis_caseworkers": [
        "AZ12345",
        "AZ234567",
        "LW1245679"
    ]
}
```

**advis_caseworkers**: The ids of caseworkers who's advis can be closed.
