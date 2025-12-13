-- Cheatsheet Toggle
-- Hotkey: Ctrl+Option+H

local cheatsheetPath = os.getenv("HOME") .. "/.productivity/cheatsheet.html"
local cheatsheetURL = "file://" .. cheatsheetPath

-- Function to find the cheatsheet window
local function findCheatsheetWindow()
    -- Get all windows from all Chrome processes
    local allWindows = hs.window.filter.new(false):setAppFilter('Google Chrome'):getWindows()

    print("Number of Chrome windows found: " .. #allWindows)
    for _, win in ipairs(allWindows) do
        local title = win:title()
        print("Checking window title: " .. (title or "nil"))
        if title and title:match("cheatsheet") then
            print("Found cheatsheet window!")
            return win
        end
    end
    return nil
end

-- Function to launch or focus cheatsheet
local function toggleCheatsheet()
    local win = findCheatsheetWindow()

    if win then
        print("Cheatsheet window found")
        -- Window exists - toggle focus
        local focusedWin = hs.window.focusedWindow()
        if focusedWin and focusedWin:id() == win:id() then
            -- Already focused, hide it
            win:application():hide()
        else
            -- Not focused, bring to front
            win:focus()
        end
    else
        print("Cheatsheet window not found")
        -- Window doesn't exist, launch it
        hs.execute('open -na "Google Chrome" --args --app=' .. cheatsheetURL)

        -- Wait for window to appear and focus it
        hs.timer.doAfter(0.5, function()
            local newWin = findCheatsheetWindow()
            if newWin then
                newWin:focus()
            end
        end)
    end
end

-- Bind hotkey: Ctrl+Option+H
hs.hotkey.bind({"ctrl", "alt"}, "h", toggleCheatsheet)

-- Show notification on load
hs.notify.new({title="Hammerspoon", informativeText="Cheatsheet hotkey: Ctrl+Option+H"}):send()

-- Auto-reload config when this file changes
hs.pathwatcher.new(os.getenv("HOME") .. "/.hammerspoon/", function(files)
    hs.reload()
end):start()

hs.alert.show("Hammerspoon config loaded")
