# Vendored Three.js

`three.module.min.js` and `three.core.min.js` are the unmodified browser ES modules from **three 0.180.0** on the npm registry. Both are required. They are served locally to avoid a runtime CDN dependency.

License: MIT; see [THREE-LICENSE.txt](THREE-LICENSE.txt).

To reproduce these files from the repository root:

```bash
npm pack three@0.180.0 --pack-destination /tmp
tar -xOf /tmp/three-0.180.0.tgz package/build/three.module.min.js > apps/office-ui/vendor/three.module.min.js
tar -xOf /tmp/three-0.180.0.tgz package/build/three.core.min.js > apps/office-ui/vendor/three.core.min.js
tar -xOf /tmp/three-0.180.0.tgz package/LICENSE > apps/office-ui/vendor/THREE-LICENSE.txt
```

The application needs no npm install or frontend build to run. npm is only needed when replacing the vendored library. Keep the module pair and license from the same release.
