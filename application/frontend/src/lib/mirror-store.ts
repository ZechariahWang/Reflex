import { create } from "zustand"

/** Mirror teleop on / off. The command block owns the switch, the main viewport shows the panel. */
export const useMirrorStore = create<{ enabled: boolean }>()(() => ({ enabled: false }))

export const setMirrorEnabled = (enabled: boolean) => useMirrorStore.setState({ enabled })
