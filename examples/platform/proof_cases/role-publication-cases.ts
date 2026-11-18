/** Authored expectations for the publisher fixture, shared by the local reader acceptances. */
export const rolePublication = {
	pack: 'platform-core',
	manifest: 'm-1',
	retainedManifest: 'm-2',
	hiddenKind: 'backup_capture',
	absentKind: 'unused_kind',
	groundRelation: 'tenant_capacity_fits',
	replQuestion: 'ask Request where true show cores',
	mcpQuestion: 'ask Request where request.cores > 0 show request.cores',
	roles: [['elm', 'reed'], ['reed', 'elm']],
} as const;
