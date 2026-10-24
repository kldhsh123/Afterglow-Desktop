import metadata from '../../version.json'

export const internalBuild = metadata.internalBuild
export const isInternalBuild = metadata.channel !== 'stable'
export const appVersion = isInternalBuild ? metadata.baseVersion + '-internal.' + internalBuild : metadata.baseVersion
