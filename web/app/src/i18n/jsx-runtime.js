import { jsx as baseJsx, jsxs as baseJsxs, Fragment } from 'react/jsx-runtime'
import { localizedProps } from './core.js'
export { Fragment }
export const jsx = (type, props, key) => baseJsx(type, localizedProps(type, props), key)
export const jsxs = (type, props, key) => baseJsxs(type, localizedProps(type, props), key)
