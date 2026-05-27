def pre_signup(event, context):
    """
    Auto-confirm user without requiring email verification.
    This simplifies the Hackathon UI flow.
    """
    event['response']['autoConfirmUser'] = True
    event['response']['autoVerifyEmail'] = True
    return event
