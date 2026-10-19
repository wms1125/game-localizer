# Original HanEngine fixture. No third-party assets are included.
define e = Character("Eileen")

label start:
    e "Hello, [player_name]!"
    "Choose a destination."
    menu:
        "Start game":
            jump begin

label begin:
    e "Welcome to the tutorial."
