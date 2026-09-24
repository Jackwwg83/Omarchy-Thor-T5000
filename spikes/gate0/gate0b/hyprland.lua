-- Gate 0b probe session: stock Hyprland look, logs on, tests started by client-tests.sh.
hl.monitor({
    output   = "",
    mode     = "preferred",
    position = "auto",
    scale    = 1,
})

hl.config({
    misc = {
        force_default_wallpaper = 0,
        disable_hyprland_logo   = false,
    },
    debug = {
        disable_logs = false,
    },
})

hl.bind("SUPER + Q", hl.dsp.exec_cmd("foot"))
hl.bind("SUPER + M", hl.dsp.exit())

hl.on("hyprland.start", function()
    hl.exec_cmd("/tmp/raytone-0b/client-tests.sh")
end)
