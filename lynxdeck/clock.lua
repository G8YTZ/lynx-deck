-- Lynx Deck station clock: draws the hands over a clock-face still.
--
-- Any still whose file name ends in "clock" (GB3OO_Clock.png, 05_clock.jpg...)
-- is treated as a face: while it is on screen this script draws the hour,
-- minute and second hands over it from the Pi's own clock (keep it on NTP).
-- The face is the Deco Gold design from G8YTZ's countdown (19 Nov 2026), and
-- the geometry below is in 1920x1080 units, matching that artwork.
--
-- Settings come from Lynx Deck with:  script-message lynxclock <offset s> <tick yes|no>
--   offset: show the time this far ahead (the coding and transmission delay)
--   tick:   second hand steps once a second instead of sweeping
-- For testing:  --script-opts=lynxclock-fixed=10:09:32  freezes the time.

local mp = require "mp"
local opts = { offset = 0, tick = "no", fixed = "" }
require("mp.options").read_options(opts, "lynxclock")

local offset = tonumber(opts.offset) or 0
local tick = opts.tick == "yes"

-- Colours as ASS wants them: &HBBGGRR&
local GOLD = "&H60B2D6&"   -- 214,178,96
local LEAD = "&H96E2FF&"   -- 255,226,150
local EDGE = "&H05080A&"   -- 10,8,5

local CX, CY = 960, 507.5  -- the dial's centre on the face
local P = 4                -- drawing in quarter pixels (\p3)

local overlay = mp.create_osd_overlay("ass-events")
overlay.res_x, overlay.res_y = 1920, 1080

-- Wall clock with sub-second precision: os.time() only gives whole seconds,
-- so note the monotonic clock at the moment the second changes and count on
-- from there. Done at start and every minute; a clock step is caught at once.
local base_wall, base_mono = nil, nil
local calibrating = nil

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

local function wall()
    if opts.fixed ~= "" then
        local h, m, s = opts.fixed:match("(%d+):(%d+):?([%d%.]*)")
        return nil, tonumber(h), tonumber(m), tonumber(s) or 0
    end
    if not base_wall then return nil end
    local t = base_wall + (mp.get_time() - base_mono) + offset
    if math.abs(math.floor(t - offset) - os.time()) > 1 then calibrate() end
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

local function draw()
    local _, h, m, s = wall()
    if not h then return end
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

mp.observe_property("filename", "string", function(_, name)
    if is_face(name) then
        if not base_wall then calibrate() end
        timer:resume()
        draw()
    else
        timer:kill()
        overlay:remove()
    end
end)

mp.register_script_message("lynxclock", function(off, tk)
    offset = tonumber(off) or 0
    tick = tk == "yes"
    mp.msg.info(string.format("clock offset %.2f s, %s", offset, tick and "ticking" or "sweeping"))
end)

calibrate()
