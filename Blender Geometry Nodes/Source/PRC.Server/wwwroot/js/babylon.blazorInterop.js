var scene = null;
var initialPts = [];
var shadowGenerator;
var gizmo;
const toolpath = {
    points: [],
    updatable: false,
};
var toolpathLines;
var hl;
var scaleMultiplier = 1.0;
var ground;

async function loadScene() {
    window.addEventListener('resize', ResizeCanvas);
    ResizeCanvas();
    const canvas = document.getElementById("renderCanvas"); // Get the canvas element
    if (canvas == null) { return; }
    canvas.style = "padding:0; margin:auto;display:block;outline: none;";

    const engine = new BABYLON.Engine(canvas, true, { stencil: true }); // Generate the BABYLON 3D engine


    scene = new BABYLON.Scene(engine);
    scene.useRightHandedSystem = true;
    //scene.debugLayer.show();
    scene.clearColor = new BABYLON.Color4(0, 0, 0, 0);

    let root = new BABYLON.TransformNode("root");
    root.rotation.x = Math.PI / 2;
    //await BABYLON.SceneLoader.ImportMeshAsync("", "data/agilus/", "agilus.gltf", scene);


    scene.createDefaultCameraOrLight(true, true, true);

    scene.activeCamera.lowerRadiusLimit = 2;
    scene.activeCamera.upperRadiusLimit = 20;
    scene.activeCamera.useAutoRotationBehavior = false;
    scene.activeCamera.alpha = 1.4;
    scene.activeCamera.beta = 1.2;
    scene.activeCamera.radius = 4 * scaleMultiplier;
    scene.activeCamera.minZ = 0.05;

    scene.activeCamera.parent = root;

    // Create SSAO and configure all properties (for the example)
    var ssaoRatio = {
        ssaoRatio: 0.5, // Ratio of the SSAO post-process, in a lower resolution
        blurRatio: 0.5// Ratio of the combine post-process (combines the SSAO and the scene)
    };

    var ssao = new BABYLON.SSAO2RenderingPipeline("ssao", scene, ssaoRatio, null, false);
    ssao.radius = 0.25;
    ssao.totalStrength = 1.3;
    ssao.expensiveBlur = false;
    ssao.samples = 16;
    scene.prePassRenderer.samples = 16;

    // Attach camera to the SSAO render pipeline
    scene.postProcessRenderPipelineManager.attachCamerasToRenderPipeline("ssao", scene.activeCamera);


    scene.lights[0].dispose();
    var light = new BABYLON.DirectionalLight("light1", new BABYLON.Vector3(-1.5, -1.5, -2.5), scene);
    light.position = new BABYLON.Vector3(4, 2, 8);
    light.shadowMinZ = 0;
    light.shadowMaxZ = 50;
    light.intensity = 1;

    shadowGenerator = new BABYLON.ShadowGenerator(2048, light)
    shadowGenerator.useBlurExponentialShadowMap = true;
    shadowGenerator.blurScale = 2;
    shadowGenerator.setDarkness(0.9);
    shadowGenerator.useKernelBlur = true;
    shadowGenerator.blurKernel = 16;
    shadowGenerator.transparencyShadow = true;

    ground = BABYLON.MeshBuilder.CreatePlane("plane", { height: 10, width: 10 });
    ground.material = new BABYLON.ShadowOnlyMaterial('mat', scene);
    ground.rotation = new BABYLON.Vector3(Math.PI, 0, 0);
    ground.material.activeLight = light;
    ground.receiveShadows = true;
    ground.flipFaces(true);


    for (var i = 0; i < scene.meshes.length; i++) {
        shadowGenerator.addShadowCaster(scene.meshes[i]);
        scene.meshes[i].receiveShadows = true;
        if (scene.meshes[i].name != "plane") {
            scene.meshes[i].enableEdgesRendering();
            scene.meshes[i].edgesWidth = 0.2;
            scene.meshes[i].edgesColor = new BABYLON.Color4(0, 0, 0, 1);
        }
    }

    /*
    var env512 = BABYLON.CubeTexture.CreateFromPrefilteredData("/images/studio_512.env", scene);
    env512.name = "env512";
    env512.gammaSpace = false;
    scene.environmentTexture = env512;
    */

    hl = new BABYLON.HighlightLayer("hl1", scene);
    hl.addExcludedMesh(ground);

    engine.runRenderLoop(function () {
        scene.render();
    });
}

function UpdateRobot(xFormsJson) {
    if (scene != null) {
        var utilLayer = new BABYLON.UtilityLayerRenderer(scene);
        const xForms = JSON.parse(xFormsJson);
        var oldLine = scene.getMeshById("line1");
        if (oldLine != null) { oldLine.dispose(); }

        var oldTCP = scene.getMeshById("tcp");
        if (oldTCP != null) { oldTCP.dispose(); }

        const points1 = [];

        for (var i = 0; i < xForms.Transformations.length; i++) {
            const matrix1 = BABYLON.Matrix.Zero();
            matrix1.setRowFromFloats(0, xForms.Transformations[i].Matrix[0], xForms.Transformations[i].Matrix[1], xForms.Transformations[i].Matrix[2], xForms.Transformations[i].Matrix[3]);
            matrix1.setRowFromFloats(1, xForms.Transformations[i].Matrix[4], xForms.Transformations[i].Matrix[5], xForms.Transformations[i].Matrix[6], xForms.Transformations[i].Matrix[7]);
            matrix1.setRowFromFloats(2, xForms.Transformations[i].Matrix[8], xForms.Transformations[i].Matrix[9], xForms.Transformations[i].Matrix[10], xForms.Transformations[i].Matrix[11]);
            matrix1.setRowFromFloats(3, xForms.Transformations[i].Matrix[12], xForms.Transformations[i].Matrix[13], xForms.Transformations[i].Matrix[14], xForms.Transformations[i].Matrix[15]);

            var robotMesh = scene.getMeshById("a" + (i).toString());
            if (robotMesh != null) {
                let matrix = robotMesh.getWorldMatrix();
                matrix.copyFrom(matrix1);
            }

            var robotMeshCenter = scene.getMeshById("c" + (i).toString());
            if (robotMeshCenter != null) {
                let matrixCenter = robotMeshCenter.getWorldMatrix();
                matrixCenter.copyFrom(matrix1);
            }

            if (i == 0) {
                ground.getWorldMatrix().copyFrom(matrix1);
            }

            points1[i] = BABYLON.Vector3.TransformCoordinates(initialPts[i], matrix1);
        }

        var centerBaseTube = BABYLON.MeshBuilder.CreateTube("line1", { path: points1, radius: 0.07 * scaleMultiplier, sideOrientation: BABYLON.Mesh.DOUBLESIDE, cap: BABYLON.Mesh.CAP_ALL, tessellation: 18 }, scene);
        shadowGenerator.addShadowCaster(centerBaseTube);

        const originalColor = new BABYLON.Color3(1.0, 0.72, 0.3);
        const darkerColor = originalColor.scale(0.8); // Reduces brightness by 20%

        hl.removeAllMeshes();
        hl.addMesh(centerBaseTube, darkerColor);
        hl.blurHorizontalSize = 0.5;
        hl.blurVerticalSize = 0.5;
        

        const blackMaterial = new BABYLON.StandardMaterial("blackMaterial", scene);
        blackMaterial.diffuseColor = new BABYLON.Color3(0.5, 0.5, 0.5);
        blackMaterial.specularColor = new BABYLON.Color3(0, 0, 0);
        blackMaterial.alpha = 0;

        centerBaseTube.material = blackMaterial;

        //toolframe
        const matrixTool = BABYLON.Matrix.Zero();
        matrixTool.setRowFromFloats(0, xForms.ToolFrame.Matrix[0], xForms.ToolFrame.Matrix[1], xForms.ToolFrame.Matrix[2], xForms.ToolFrame.Matrix[3]);
        matrixTool.setRowFromFloats(1, xForms.ToolFrame.Matrix[4], xForms.ToolFrame.Matrix[5], xForms.ToolFrame.Matrix[6], xForms.ToolFrame.Matrix[7]);
        matrixTool.setRowFromFloats(2, xForms.ToolFrame.Matrix[8], xForms.ToolFrame.Matrix[9], xForms.ToolFrame.Matrix[10], xForms.ToolFrame.Matrix[11]);
        matrixTool.setRowFromFloats(3, xForms.ToolFrame.Matrix[12], xForms.ToolFrame.Matrix[13], xForms.ToolFrame.Matrix[14], xForms.ToolFrame.Matrix[15]);

        var tcp = BABYLON.MeshBuilder.CreateSphere("tcp", { diameter: 0.010 });


        if (tcp != null) {
            let matrixCenter = tcp.getWorldMatrix();
            matrixCenter.copyFrom(matrixTool);
        }

        if (gizmo != null) {
            gizmo.dispose();
        }
        gizmo = new BABYLON.PositionGizmo(utilLayer);
        gizmo.xGizmo.dragBehavior.onDragObservable.clear();
        gizmo.yGizmo.dragBehavior.onDragObservable.clear();
        gizmo.zGizmo.dragBehavior.onDragObservable.clear();
        gizmo.attachedMesh = tcp;
    }
}

function SetupRobot(robotData) {
    if (scene != null) {

        for (var i = 0; i < scene.meshes.length; i++) {
            if (scene.meshes[i].id != "plane") {
                scene.meshes[i].dispose();
                i--;
            }
        }

        const robotDataJSON = JSON.parse(robotData);

        

        //get main distance base to flange
        const basePt = new BABYLON.Vector3(robotDataJSON.AxisCenter[0].X / 1000, robotDataJSON.AxisCenter[0].Y / 1000, robotDataJSON.AxisCenter[0].Z / 1000);
        const a04Pt = new BABYLON.Vector3(robotDataJSON.AxisCenter[3].X / 1000, robotDataJSON.AxisCenter[3].Y / 1000, robotDataJSON.AxisCenter[3].Z / 1000);

        scaleMultiplier = BABYLON.Vector3.Distance(basePt, a04Pt);
        scene.activeCamera.radius = 4 * scaleMultiplier;

        var markerThicknessDivider = 100 * scaleMultiplier;
        var markerRadius = 0.07 * scaleMultiplier;

        var centerThicknessDivider = 50 * scaleMultiplier;
        var centerRadius = 0.06 * scaleMultiplier;

        initialPts = [];

        //create materials
        const whiteMaterial = new BABYLON.StandardMaterial("whiteMaterial", scene);
        whiteMaterial.diffuseColor = new BABYLON.Color3(0.99, 0.99, 0.99);
        whiteMaterial.specularColor = new BABYLON.Color3(0.5, 0.6, 0.87);
        whiteMaterial.emissiveColor = new BABYLON.Color3(1, 1, 1);
        whiteMaterial.ambientColor = new BABYLON.Color3(0.75, 0.75, 0.75);
        whiteMaterial.alpha = 1.0;

        const blackMaterial = new BABYLON.StandardMaterial("blackMaterial", scene);
        blackMaterial.diffuseColor = new BABYLON.Color3(0, 0, 0);
        blackMaterial.specularColor = new BABYLON.Color3(0, 0, 0);
        blackMaterial.emissiveColor = new BABYLON.Color3(0, 0, 0);
        blackMaterial.ambientColor = new BABYLON.Color3(0.23, 0.98, 0.53);



        //build base
        var basePath = [
            new BABYLON.Vector3(0, 0, 1 / markerThicknessDivider * -1 * 1.5),
            new BABYLON.Vector3(0, 0, 1 / markerThicknessDivider * 1.5)
        ];
        var baseTube = BABYLON.MeshBuilder.CreateTube("a0", { path: basePath, radius: markerRadius * 2, sideOrientation: BABYLON.Mesh.DOUBLESIDE, cap: BABYLON.Mesh.CAP_ALL, tessellation: 3 }, scene);
        baseTube.material = whiteMaterial;
        shadowGenerator.addShadowCaster(baseTube);

        var centerBasePath = [
            new BABYLON.Vector3(0, 0, 1 / centerThicknessDivider * -1 * 1.5),
            new BABYLON.Vector3(0, 0, 1 / centerThicknessDivider * 1.5)
        ];
        //var centerBaseTube = BABYLON.MeshBuilder.CreateTube("c0", { path: centerBasePath, radius: centerRadius, sideOrientation: BABYLON.Mesh.DOUBLESIDE, cap: BABYLON.Mesh.CAP_ALL, tessellation: 4 }, scene);
        //centerBaseTube.material = blackMaterial;

        initialPts[0] = new BABYLON.Vector3(0, 0, 0);

        for (var i = 0; i < robotDataJSON.AxisCenter.length; i++) {
            var markerPath = [
                new BABYLON.Vector3(robotDataJSON.AxisCenter[i].X / 1000 - robotDataJSON.AxisDirection[i].X / markerThicknessDivider, robotDataJSON.AxisCenter[i].Y / 1000 - robotDataJSON.AxisDirection[i].Y / markerThicknessDivider, robotDataJSON.AxisCenter[i].Z / 1000 - robotDataJSON.AxisDirection[i].Z / markerThicknessDivider),
                new BABYLON.Vector3(robotDataJSON.AxisCenter[i].X / 1000 + robotDataJSON.AxisDirection[i].X / markerThicknessDivider, robotDataJSON.AxisCenter[i].Y / 1000 + robotDataJSON.AxisDirection[i].Y / markerThicknessDivider, robotDataJSON.AxisCenter[i].Z / 1000 + robotDataJSON.AxisDirection[i].Z / markerThicknessDivider),

            ];

            if (i == robotDataJSON.AxisCenter.length - 1) { markerRadius = markerRadius * 1.5; }

            var marker1 = BABYLON.MeshBuilder.CreateTube("a" + (i + 1).toString(), { path: markerPath, radius: markerRadius, sideOrientation: BABYLON.Mesh.DOUBLESIDE, cap: BABYLON.Mesh.CAP_ALL, }, scene);
            marker1.material = whiteMaterial;
            marker1.alwaysSelectAsActiveMesh = true;


            var centerPath = [
                new BABYLON.Vector3(robotDataJSON.AxisCenter[i].X / 1000 - robotDataJSON.AxisDirection[i].X / centerThicknessDivider, robotDataJSON.AxisCenter[i].Y / 1000 - robotDataJSON.AxisDirection[i].Y / centerThicknessDivider, robotDataJSON.AxisCenter[i].Z / 1000 - robotDataJSON.AxisDirection[i].Z / centerThicknessDivider),
                new BABYLON.Vector3(robotDataJSON.AxisCenter[i].X / 1000 + robotDataJSON.AxisDirection[i].X / centerThicknessDivider, robotDataJSON.AxisCenter[i].Y / 1000 + robotDataJSON.AxisDirection[i].Y / centerThicknessDivider, robotDataJSON.AxisCenter[i].Z / 1000 + robotDataJSON.AxisDirection[i].Z / centerThicknessDivider),

            ];
            var marker2 = BABYLON.MeshBuilder.CreateTube("c" + (i + 1).toString(), { path: centerPath, radius: centerRadius, sideOrientation: BABYLON.Mesh.DOUBLESIDE, cap: BABYLON.Mesh.CAP_ALL, tessellation: 16 }, scene);

            marker2.material = blackMaterial;
            marker2.alwaysSelectAsActiveMesh = true;

            initialPts[i + 1] = new BABYLON.Vector3(robotDataJSON.AxisCenter[i].X / 1000, robotDataJSON.AxisCenter[i].Y / 1000, robotDataJSON.AxisCenter[i].Z / 1000);

        }
    }
}

function UpdateToopath(toolpathData) {
    if (scene != null) {
        if (toolpathLines != null) {
            toolpathLines.dispose();
        }
        const toolpathDataJSON = JSON.parse(toolpathData);
        var pts = [];
        var clr = [];
        for (var i = 0; i < toolpathDataJSON.Points.length; i++) {
            pts.push(new BABYLON.Vector3(toolpathDataJSON.Points[i].X / 1000.0, toolpathDataJSON.Points[i].Y / 1000.0, toolpathDataJSON.Points[i].Z / 1000.0));

            if (toolpathDataJSON.Alarm[i] == true) {
                clr.push(new BABYLON.Color4(1, 0, 0, 1));
            }
            else {
                clr.push(new BABYLON.Color4(0.7, 0.7, 0.7, 1));
            }
        }

        toolpath.points = pts;
        toolpath.colors = clr;

        toolpathLines = BABYLON.MeshBuilder.CreateLines("toolpath", toolpath, scene);
    }
}

function ResizeCanvas() {
    var canvas = document.getElementById('renderCanvas');
    if (canvas != null) {
        canvas.width = window.innerWidth / 1.5;
        canvas.height = window.innerHeight / 1.3;
    }
}

window.BabylonBlazorInteropFunctions = {
    load: () => { loadScene(); },
    resize: () => { ResizeCanvas(); },
    update: (xFormsJson) => { UpdateRobot(xFormsJson); },
    setup: (robotData) => { SetupRobot(robotData); },
    toolpath: (toolpathData) => { UpdateToopath(toolpathData); }
};