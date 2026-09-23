// Original fixture: no vendor code, credentials, or device identifiers.
public struct RobotSettings {
    public var volume: Int
    public var muted: Bool
    public init(volume: Int, muted: Bool) {
        self.volume = volume
        self.muted = muted
    }
}
@inline(never)
public func nextVolume(_ current: Int) -> Int { min(100, current + 5) }
