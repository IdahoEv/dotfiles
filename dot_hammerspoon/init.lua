-- Cheatsheet Toggle
-- Hotkey: Ctrl+Option+H

local cheatsheetPath = os.getenv("HOME") .. "/.productivity/cheatsheet.html"
local cheatsheetURL = "file://" .. cheatsheetPath

-- Function to find the cheatsheet window
local function findCheatsheetWindow()
    local startTime = hs.timer.secondsSinceEpoch()

    -- Use direct window finding instead of window filter
    local chromeApp = hs.application.find('Google Chrome')
    local afterFindApp = hs.timer.secondsSinceEpoch()
    print(string.format("Finding Chrome app took %.3f seconds", afterFindApp - startTime))

    if not chromeApp then
        print("Chrome not running")
        return nil
    end

    local allWindows = chromeApp:allWindows()
    local afterGetWindows = hs.timer.secondsSinceEpoch()
    print(string.format("Getting windows took %.3f seconds", afterGetWindows - afterFindApp))

    print("Number of Chrome windows found: " .. #allWindows)
    for _, win in ipairs(allWindows) do
        local title = win:title()
        print("Checking window title: " .. (title or "nil"))
        if title and title:match("cheatsheet") then
            print("Found cheatsheet window!")
            local endTime = hs.timer.secondsSinceEpoch()
            print(string.format("Total findCheatsheetWindow() took %.3f seconds", endTime - startTime))
            return win
        end
    end
    local endTime = hs.timer.secondsSinceEpoch()
    print(string.format("Total findCheatsheetWindow() took %.3f seconds", endTime - startTime))
    return nil
end

-- Function to position window in center of primary screen
local function positionCheatsheet(win)
    -- Get primary screen frame
    local screen = hs.screen.primaryScreen()
    local screenFrame = screen:frame()

    -- Set window size (adjust these values as needed)
    local windowWidth = 1000
    local windowHeight = 800

    -- Calculate center position
    local x = screenFrame.x + (screenFrame.w - windowWidth) / 2
    local y = screenFrame.y + (screenFrame.h - windowHeight) / 2

    -- Position and size the window
    win:setFrame({
        x = x,
        y = y,
        w = windowWidth,
        h = windowHeight
    })
end

-- Function to launch or focus cheatsheet
local function toggleCheatsheet()
    local startTime = hs.timer.secondsSinceEpoch()
    print("=== toggleCheatsheet called ===")

    local win = findCheatsheetWindow()
    local afterFind = hs.timer.secondsSinceEpoch()

    if win then
        print("Cheatsheet window found")
        -- Window exists - toggle focus
        local focusedWin = hs.window.focusedWindow()
        if focusedWin and focusedWin:id() == win:id() then
            -- Already focused, hide it
            win:minimize()
        else
            -- Not focused, unminimize if needed, position, and bring to front
            if win:isMinimized() then
                win:unminimize()
            end
            positionCheatsheet(win)
            win:focus()
        end
        local endTime = hs.timer.secondsSinceEpoch()
        print(string.format("Total toggleCheatsheet took %.3f seconds", endTime - startTime))
    else
        print("Cheatsheet window not found")
        -- Window doesn't exist, launch it
        local beforeLaunch = hs.timer.secondsSinceEpoch()
        hs.execute('open -na "Google Chrome" --args --app=' .. cheatsheetURL)
        local afterLaunch = hs.timer.secondsSinceEpoch()
        print(string.format("Launch command took %.3f seconds", afterLaunch - beforeLaunch))

        -- Wait for window to appear, position it immediately, ansd focus it
        hs.timer.doAfter(0.5, function()
            local newWin = findCheatsheetWindow()
            if newWin then
                positionCheatsheet(newWin)
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
