-- Lynx Deck station clock: draws the hands over a clock-face still.
--
-- Any still whose file name ends in "clock" (GB3OO_Clock.png, 05_clock.jpg...)
-- is treated as a face: while it is on screen this script draws the hour,
-- minute and second hands over it from the Pi's own clock (keep it on NTP).
-- The face is the Deco Gold design from G8YTZ's countdown (19 Nov 2026), and
-- the geometry below is in 1920x1080 units, matching that artwork.
--
-- Settings come from Lynx Deck with:  script-message lynxclock <offset s> <tick yes|no> <sounds dir>
--   offset: show the time this far ahead (the coding and transmission delay)
--   tick:   second hand steps once a second instead of sweeping
-- For testing:  --script-opts=lynxclock-fixed=10:09:32  freezes the time;
--                --script-opts=lynxclock-start=10:59:20  runs it from there.
--
-- At the top of the hour, while the clock is playing (not just cued), it adds
-- the sound: clock/junction/junction_HH.flac (clock/make_junction.py), which
-- starts at mm:59:30, pips from :55, the long pip on the hour, then the time.

local mp = require "mp"
local opts = { offset = 0, tick = "no", fixed = "", start = "" }
require("mp.options").read_options(opts, "lynxclock")

local offset = tonumber(opts.offset) or 0
-- The Pi's picture runs behind its sound, so Lynx Deck holds the sound back
-- with mpv's audio-delay. That cannot work here: this script keeps seeking
-- the junction to the wall clock, which cancels it (GB3JT, 25 Nov 2026).
-- So the junction carries the same delay itself, in where it seeks to.
local sound_delay = 0
local tick = opts.tick == "yes"

-- Colours as ASS wants them: &HBBGGRR&
local GOLD = "&H60B2D6&"   -- 214,178,96
local LEAD = "&H96E2FF&"   -- 255,226,150
local EDGE = "&H05080A&"   -- 10,8,5

local CX, CY = 960, 507.5  -- the dial's centre on the face
local P = 4                -- drawing in quarter pixels (\p3)

-- What the script is doing, for Lynx Deck and for tools/clock-check.py:
-- mpv's user-data is readable over the same socket, so no log is needed.
local function note(key, value)
    pcall(mp.set_property, "user-data/lynxclock/" .. key, tostring(value))
end

local overlay = mp.create_osd_overlay("ass-events")
overlay.res_x, overlay.res_y = 1920, 1080

-- Wall clock with sub-second precision: os.time() only gives whole seconds,
-- so note the monotonic clock at the moment the second changes and count on
-- from there. Done at start and every minute; a clock step is caught at once.
local base_wall, base_mono = nil, nil
local calibrating = nil
local off_since = nil

local function calibrate()
    if calibrating then return end
    local first = os.time()
    calibrating = mp.add_periodic_timer(0.002, function()
        local now = os.time()
        if now ~= first then
            base_wall, base_mono = now, mp.get_time()
            calibrating:kill()
            calibrating = nil
        end
    end)
end

local function hms(text)
    local h, m, s = text:match("(%d+):(%d+):?([%d%.]*)")
    return tonumber(h), tonumber(m), tonumber(s) or 0
end
local started = mp.get_time()

local function wall()
    if opts.fixed ~= "" then
        local h, m, s = hms(opts.fixed)
        return nil, h, m, s
    end
    if opts.start ~= "" then
        local h, m, s = hms(opts.start)
        local t = h * 3600 + m * 60 + s + (mp.get_time() - started)
        return t, math.floor(t / 3600) % 24, math.floor(t / 60) % 60, t % 60
    end
    if not base_wall then return nil end
    local t = base_wall + (mp.get_time() - base_mono) + offset
    -- floor(t) and os.time() can differ by one across a second boundary, so a
    -- single disagreement means nothing; a real step holds. Recalibrate once it
    -- has held for half a second (Justin, 25 Nov 2026: a one second step on
    -- GB3OO was missed by the old > 1 test, and the clock and the pips ran a
    -- second fast until the next minute's resync).
    if math.abs(math.floor(t - offset) - os.time()) >= 1 then
        off_since = off_since or mp.get_time()
        if mp.get_time() - off_since > 0.5 then
            off_since = nil
            calibrate()
        end
    else
        off_since = nil
    end
    local whole = math.floor(t)
    local d = os.date("*t", whole)
    return t, d.hour, d.min, d.sec + (t - whole)
end

-- (along, across) from the centre, along pointing at 12, turned by deg.
local function pt(along, across, deg)
    local a = math.rad(deg)
    local x = CX + along * math.sin(a) + across * math.cos(a)
    local y = CY - along * math.cos(a) + across * math.sin(a)
    return string.format("%d %d", math.floor(x * P + 0.5), math.floor(y * P + 0.5))
end

local function shape(points, deg, colour, border)
    local s = { string.format("{\\an7\\pos(0,0)\\shad0\\bord%s\\3c%s\\1c%s\\p3}m ",
                              border, EDGE, colour) }
    for i, p in ipairs(points) do
        s[#s + 1] = pt(p[1], p[2], deg)
        s[#s + 1] = (i == 1) and " l " or " "
    end
    s[#s + 1] = "{\\p0}"
    return table.concat(s)
end

local function circle(along, r, deg, colour, border)
    local pts = {}
    for i = 0, 31 do
        local a = 2 * math.pi * i / 32
        pts[#pts + 1] = { along + r * math.cos(a), r * math.sin(a) }
    end
    return shape(pts, deg, colour, border)
end

-- A Deco lozenge hand, widest a third of the way out, with a fine spine.
local function hand(deg, len, wid, tail)
    local k = wid / 2
    return {
        shape({ { -tail, 0 }, { 0, k * 0.45 }, { len * 0.32, k }, { len, 0 },
                { len * 0.32, -k }, { 0, -k * 0.45 } }, deg, GOLD, 1),
        shape({ { len * 0.1, 0.5 }, { len * 0.9, 0.5 }, { len * 0.9, -0.5 },
                { len * 0.1, -0.5 } }, deg, EDGE, 0),
    }
end

-- Fade up from black when the face arrives, so face and hands appear as one.
-- The black goes up as the file loads (before its first frame), and starts
-- to fade once mpv says the picture is showing.
local FADE = 0.5          -- seconds
local fading = nil        -- nil, "black" (waiting for the picture) or the fade's start time
local BLACK = "{\\an7\\pos(0,0)\\shad0\\bord0\\1c&H000000&\\alpha&H%02X&\\p1}m 0 0 l 1920 0 1920 1080 0 1080{\\p0}"

local function black(alpha)
    return string.format(BLACK, alpha)
end

-- The top of the hour: sound from 30 s before the hour, kept to the clock.
-- A still has no timeline of its own, and a sound added to it would end the
-- "file" when it finished (the Deck would see the clip end and stop). So the
-- face gets an endless silent track as it loads, the hour's sound is switched
-- in at 59:30 and the silence switched back before the sound runs out.
local AHEAD, LENGTH = 30, 35    -- the sound starts 30 s before the hour
-- Normally the junction goes out on the hour. Test mode (lynxclock-test)
-- puts the junction on every minute instead, otherwise unchanged, so a
-- timing fault can be chased a minute at a time instead of an hour.
local PERIOD = 3600
local testing = false
local here = debug.getinfo(1, "S").source:gsub("^@", ""):gsub("[^/]*$", "")
local generic_dir = here .. "../clock/junction/"   -- pips only, for any Deck
local own_dir = nil                                -- this Deck's own (Lynx Deck tells us)
local bed_track, junction_track, fired_for, warned_for, check_at = nil, nil, nil, nil, nil

local function add_bed()
    -- 32-bit float: lavfi's silence is 8-bit by default, and mpv opens the
    -- sound output in the format of the first track, so the hour's sound
    -- then played through an 8-bit output (audible quantising noise,
    -- Justin, 20 Nov 2026).
    mp.commandv("audio-add", "av://lavfi:anullsrc=r=48000:cl=stereo,aformat=sample_fmts=flt",
                "select", "silence")
    bed_track = mp.get_property_number("aid")
end

local function junction(h, m, s)
    local t = h * 3600 + m * 60 + s
    local hour_mark = math.floor((t + AHEAD) / PERIOD) * PERIOD
    local pos = t + AHEAD - hour_mark            -- seconds into the sound
    if junction_track and mp.get_property_number("aid") == junction_track then
        if pos >= LENGTH - 0.5 then
            mp.set_property_number("aid", bed_track)  -- back to silence before it ends
        elseif check_at and mp.get_time() >= check_at then
            check_at = nil
            local a = mp.get_property_number("audio-pts")
            if a and math.abs(a - (pos - sound_delay)) > 0.03 then
                mp.commandv("seek", string.format("%.3f", pos - sound_delay), "absolute+exact")
                mp.msg.info(string.format("top of the hour sound %.3f s out: corrected", a - pos))
            end
        end
        return
    end
    if pos >= LENGTH - 1 or fired_for == hour_mark or not bed_track then return end
    if mp.get_property_bool("pause") then
        if warned_for ~= hour_mark then
            warned_for = hour_mark
            mp.msg.warn("clock cued but not playing: no top-of-the-hour sound yet")
        end
        return
    end
    fired_for = hour_mark
    local hour = math.floor(hour_mark / 3600) % 12
    if hour == 0 then hour = 12 end
    -- this Deck's own first, then the generic ones; lossless .flac, or the
    -- .m4a that 1.6 and 1.7 built until the sounds are rebuilt
    local file = nil
    for _, dir in ipairs({ own_dir or "", generic_dir }) do
        for _, ext in ipairs({ "flac", "m4a" }) do
            local path = string.format("%sjunction_%02d.%s", dir, hour, ext)
            local f = dir ~= "" and io.open(path, "rb")
            if f then f:close(); file = file or path end
        end
    end
    file = file or string.format("%sjunction_%02d.flac", generic_dir, hour)
    if junction_track then mp.commandv("audio-remove", tostring(junction_track)) end
    mp.commandv("audio-add", file, "select", "top of the hour")
    junction_track = mp.get_property_number("aid")
    if junction_track == bed_track then         -- the file was not there
        junction_track = nil
        mp.msg.warn("no top-of-the-hour sound: " .. file)
        return
    end
    mp.commandv("seek", string.format("%.3f", pos - sound_delay), "absolute+exact")
    check_at = mp.get_time() + 1
    note("file", file)
    note("sound-delay", sound_delay)
    note("fired-at", string.format("%.3f", pos))
    mp.msg.info(string.format("top of the hour: %s from %.2f s", file, pos))
end

-- Fade to black before a scheduled cut (Lynx Deck's schedule asks, a
-- second ahead); the black stays until the next clip's picture replaces it.
local fade_out = nil      -- {start, seconds}

local function draw()
    local _, h, m, s = wall()
    if h and fading ~= "black" then junction(h, m, s) end
    if fading == "black" or not h then
        overlay.data = black(0)
        overlay:update()
        return
    end
    if tick then s = math.floor(s) end
    local mins = m + s / 60
    local hrs = (h % 12) + mins / 60
    local ev = {}
    for _, e in ipairs(hand(hrs * 30, 200, 30, 34)) do ev[#ev + 1] = e end
    for _, e in ipairs(hand(mins * 6, 305, 20, 40)) do ev[#ev + 1] = e end
    local a = s * 6
    ev[#ev + 1] = shape({ { -80, 1.5 }, { 318, 1.5 }, { 318, -1.5 }, { -80, -1.5 } }, a, LEAD, 0)
    ev[#ev + 1] = shape({ { 262 - 11, 0 }, { 262, 7.7 }, { 262 + 11, 0 }, { 262, -7.7 } }, a, LEAD, 0)
    ev[#ev + 1] = circle(-62, 10, a, LEAD, 0)
    ev[#ev + 1] = circle(0, 15, 0, LEAD, 0.5)
    ev[#ev + 1] = circle(0, 5, 0, EDGE, 0)
    if fade_out then
        local k = math.min(1, (mp.get_time() - fade_out[1]) / fade_out[2])
        ev[#ev + 1] = black(math.floor(255 * (1 - k)))
    elseif fading then
        local k = (mp.get_time() - fading) / FADE
        if k >= 1 then
            fading = nil
        else
            ev[#ev + 1] = black(math.floor(255 * k * k))   -- eased: slow out of black
        end
    end
    overlay.data = table.concat(ev, "\n")
    overlay:update()
end

local timer = mp.add_periodic_timer(0.02, draw)   -- 50 a second; the output takes what it needs
timer:kill()
local resync = mp.add_periodic_timer(60, calibrate)

local function is_face(name)
    if not name then return false end
    local stem = name:lower():match("^(.-)%.[^.]+$") or name:lower()
    return stem:match("clock$") ~= nil
end

-- On: black as the face file loads, fade once its picture shows.
-- Off: the hands stay until the next clip's picture shows, then go.
local showing = false

mp.register_event("file-loaded", function()
    if is_face(mp.get_property("filename")) then
        if not base_wall then calibrate() end
        showing, fading = true, "black"
        fired_for, warned_for, junction_track, check_at = nil, nil, nil, nil
        fade_out = nil
        add_bed()                                -- a new file: its own silent track
        timer:resume()
        draw()
    end
end)

mp.register_event("playback-restart", function()
    if is_face(mp.get_property("filename")) then
        if fading == "black" then fading = mp.get_time() end
    elseif showing then
        showing, fading = false, nil
        timer:kill()
        overlay:remove()
    end
end)

mp.observe_property("idle-active", "bool", function(_, idle)
    if idle and showing then
        showing, fading = false, nil
        timer:kill()
        overlay:remove()
    end
end)

mp.register_script_message("lynxclock-fadeout", function(secs)
    if showing then fade_out = { mp.get_time(), math.max(0.1, tonumber(secs) or 1) } end
end)

-- Pips on every minute, for testing: the generic pips-only file, no music
-- and no announcement. Leave the face on screen and listen.
mp.register_script_message("lynxclock-test", function(on)
    testing = on ~= "no"
    PERIOD = testing and 60 or 3600
    fired_for, warned_for, check_at = nil, nil, nil
    if junction_track then
        if bed_track then mp.set_property_number("aid", bed_track) end
        mp.commandv("audio-remove", tostring(junction_track))
        junction_track = nil
    end
    note("period", PERIOD)
    mp.msg.info(testing and "clock test: the junction every minute"
                        or "clock test off: the junction on the hour")
end)

-- Lynx Deck's scheduler saw the system clock step: take its word for it
-- rather than waiting to notice.
mp.register_script_message("lynxclock-recalibrate", function()
    off_since = nil
    calibrate()
    mp.msg.info("clock step reported: recalibrating")
end)

mp.register_script_message("lynxclock", function(off, tk, dir, delay)
    sound_delay = tonumber(delay) or 0
    offset = tonumber(off) or 0
    tick = tk == "yes"
    if dir and dir ~= "" then own_dir = dir end
    note("own-dir", own_dir or "(none: the generic pips)")
    note("offset", offset)
    mp.msg.info(string.format("clock offset %.2f s, %s", offset, tick and "ticking" or "sweeping"))
end)

calibrate()

note("own-dir", "(none yet)")
note("ready", "yes")      -- Lynx Deck waits for this before sending settings
