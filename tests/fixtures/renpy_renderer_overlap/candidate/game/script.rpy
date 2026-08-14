screen main_menu():
    tag menu

    add Solid("#20242a")
    text "Primary localization control" xpos 80 ypos 220 size 40
    text "Secondary localization control" xpos 250 ypos 220 size 40

label main_menu_screen:
    call screen main_menu
    return

label start:
    "Fixture runtime"
    jump start
