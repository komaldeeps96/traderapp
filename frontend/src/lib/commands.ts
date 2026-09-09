/**
 * Where the store posts commands to the server.
 *
 * The store is plain state and the socket lives in `useTerminal`, but toggling
 * an indicator is a store action that must reach the backend. A module-level
 * sink rather than a store field, because a live socket handle is not state a
 * component should re-render on.
 *
 * With no sink installed — unit tests, or before the terminal mounts —
 * commands are dropped rather than throwing; the socket replays on connect.
 */

import type { ClientCommand } from '@/types/protocol';

let sink: ((command: ClientCommand) => void) | null = null;

export function setCommandSink(next: ((command: ClientCommand) => void) | null): void {
  sink = next;
}

export function sendCommand(command: ClientCommand): void {
  sink?.(command);
}
