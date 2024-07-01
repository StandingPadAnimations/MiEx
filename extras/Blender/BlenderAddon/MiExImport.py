import bpy
from bpy_extras.io_utils import ImportHelper
from bpy.props import StringProperty, EnumProperty, IntProperty, BoolProperty
from bpy.types import Operator
import pxr.Usd as Usd

import os, json, warnings, math

bl_info = {
    "name" : "MiEx Import",
    "author" : "michael212345, Bram Stout",
    "version" : (0, 1, 0),
    "blender" : (4, 0, 0),
    "description" : "This addon allows you to import in USD exports generated by MiEx.",
    "wiki_url" : "https://github.com/BramStoutProductions/MiEx/",
}

class setup_materials:

    def __init__(self, mat : bpy.types.Material, data, rootDir, options):
        self.conn_to_make = []
        self.mat = mat        # delete all nodes in material
        self.mat.use_nodes = True
        self.rootDir = rootDir
        self.hasTransparency = False
        self.options = options

        for node in self.mat.node_tree.nodes:
            self.mat.node_tree.nodes.remove(node)

        for name, node_data in data['network'].items():
            try:
                self.import_node(name,node_data)
            except Exception as e:
                warnings.warn('Failed to create node: ' + name, UserWarning)
                raise e

        for conn in self.conn_to_make:
            try:
                node0, attr0 = conn[0].split(".")
                node1, attr1 = conn[1].split(".")
                
                node0 = self.get_Node_By_Name(node0)
                node1 = self.get_Node_By_Name(node1)

                self.mat.node_tree.links.new(node0.outputs[attr0], node1.inputs[attr1])
            except Exception as e:
                warnings.warn('Failed to make connection: ' + str(conn), UserWarning)
                raise e

        for name, attr in data['terminals'].items():
            try:
                inputAttr = attr
                inputAttr = inputAttr.split("/")
                inputAttr = inputAttr[len(inputAttr)-1]
                output = self.get_output_node()
                self.mat.node_tree.links.new(self.get_Node_By_Name(inputAttr.split('.')[0]).outputs[inputAttr.split('.')[-1]], output.inputs[0])
            except Exception as e:
                warnings.warn('Failed to connect terminal: ' + name, UserWarning)
                raise e
        
        mat.use_backface_culling = True
        if self.hasTransparency:
            self.mat.blend_method = 'BLEND'
            self.mat.shadow_method = 'HASHED'

    def import_node(self,name,data):
        node = self.mat.node_tree.nodes.new(data['type'])
        node.name = name
        node.label = name
        isBsdf = 'Bsdf' in data['type']


        if 'attributes' in data:
            for attrName, attrData in data['attributes'].items():
                try:
                    if isBsdf and attrName == "Alpha":
                        self.hasTransparency = True

                    if attrData["type"] == "asset":
                        imagePath = attrData['value']
                        if not os.path.exists(imagePath):
                            imagePath = os.path.join(self.rootDir, imagePath)
                            if not os.path.exists(imagePath):
                                continue # Image doesn't exist, so just don't load it.
                        node.image = bpy.data.images.load(imagePath)
                    elif 'value' in attrData:
                        if hasattr(node, attrName):
                            setattr(node, attrName, attrData['value'])
                        elif attrName in node.inputs:
                            node.inputs[attrName].default_value = attrData['value']
                        else:
                            node[attrName] = attrData['value']
                    elif 'connection' in attrData:
                        inputAttr = attrData["connection"]
                        inputAttr = inputAttr.split("/")
                        inputAttr = inputAttr[len(inputAttr)-1]
                        self.conn_to_make.append((inputAttr, node.name + "." + attrName))

                    elif "keyframes" in attrData:
                        keyframes = attrData["keyframes"]
                        numFrames = len(keyframes) // 2
                        i = 0
                        inputobject = node.inputs[attrName]
                        if attrData["type"] == "Float":
                            while i < numFrames:
                                
                                if i >= self.options['max_animation_frames']:
                                    break
                                
                                inputobject.default_value = keyframes[i * 2 + 1]
                                inputobject.keyframe_insert(data_path="default_value", frame=math.floor(keyframes[i * 2]*10.0)/10.0)
                                
                                i += 1
                        
                        
                except Exception as e:
                    warnings.warn('Failed to set attribute: ' + attrName, UserWarning)
                    raise e

    def get_output_node(self):
        material_output = None
        for node in self.mat.node_tree.nodes:
            if node.type == "OUTPUT_MATERIAL":
                material_output = node
                break
        if material_output is None:
            material_output = self.mat.node_tree.nodes.new('ShaderNodeOutputMaterial')
        return material_output

    def get_Node_By_Name(self, name:str):
        for node in self.mat.node_tree.nodes:
            if node.name == name:
                return node
        raise Exception("Node not found: " + name)

def is_render_mesh(mesh: bpy.types.Object):
    parent = mesh.parent
    
    if parent is None:
        return False
    
    chunkGroup = parent.parent
    
    if chunkGroup is None:
        return False
    
    parentName = parent.name.split('.')[0]
    proxyName = parentName + '_proxy'
    for child in chunkGroup.children:
        if child.name.startswith(proxyName):
            return True
    
    return False
    

def read_data(context, filepath, options: dict):

    directory = os.path.dirname(filepath)
    filename = os.path.basename(filepath).split('.')[0]
    # Look for material json file
    materialJson = os.path.join(directory, filename + '_materials.json')
    
    if not os.path.exists(materialJson):
        
        # Warning popup
        message = "Material file not found: " + materialJson
        warnings.warn(message, UserWarning)
        
        return {'CANCELLED'}
    
    # Read material json file
    with open(materialJson) as f:
        materials = json.load(f)

    # Get mesh list before import
    meshes = set(o for o in bpy.context.scene.objects if o.type == 'MESH')
    mats = set(bpy.data.materials.keys())

    if options['import_type'] == 'proxy':
        Usd.Stage.SetGlobalVariantFallbacks({"MiEx_LOD": ["proxy"]})
    else:
        Usd.Stage.SetGlobalVariantFallbacks({"MiEx_LOD": ["render"]}) 
    
    bpy.ops.wm.usd_import(filepath=filepath, scale=1.0/16.0, mtl_name_collision_mode='REFERENCE_EXISTING',import_proxy=bool(options['import_type'] != 'render'))

    # Make a filtered list of meshes that were imported
    meshes = set(o for o in bpy.context.scene.objects if o.type == 'MESH' and o not in meshes)
    mats = set(o for o in bpy.data.materials.keys() if o not in mats)
    # Filter meshes based on import type
    for mesh in meshes:
        
        if options['flatten']:
            mesh.data.polygons.foreach_set("use_smooth", [False] * len(mesh.data.polygons))
        
        if len(mesh.data.materials) > 0:
            mat = mesh.data.materials[0]
            meshAttributes = mesh.data.attributes
            if 'displayColor' in meshAttributes:
                displayColor = meshAttributes['displayColor'].data[0].color
                # Quickly do a gamma correction
                displayColorSRGB = [ pow(displayColor[0], 1.0/2.2), 
                                        pow(displayColor[1], 1.0/2.2), 
                                        pow(displayColor[2], 1.0/2.2), 1.0 ]
                mat.diffuse_color = displayColorSRGB
        if options['import_type'] == 'both':
            # Show proxy in viewport but not render
            if mesh.name.split('.')[0].endswith('_proxy'):
                mesh.hide_render = True
            # Show render in render but not viewport
            elif is_render_mesh(mesh):
                mesh.hide_viewport = True

    # Finally we can set up mats
    for key,val in materials.items():
        try:
            if key not in mats:
                continue # Skip already existing materials

            mat = bpy.data.materials[key]

            if mat is None:
                warnings.warn('Material not found: ' + key, UserWarning)
                continue

            setup_materials(mat, val, directory, options)
        except Exception as e:
            warnings.warn('Material failed: ' + key, UserWarning)
            raise e

    return {'FINISHED'}

class MiexImport(Operator, ImportHelper):
    bl_idname = "mieximport.world"
    bl_label = "Import MiEx (.usd)"
    filename_ext = ".usd"  # Specify the file extension
    
    filter_glob: StringProperty(
        default="*.usd",
        options={'HIDDEN'},
        maxlen=255
    )
    
    import_type: EnumProperty(
        name="Import type",
        description="Import either proxy or render variant",
        items=(
            ('proxy', "Proxy", "Import proxy models only"),
            ('render', "Render", "Import render models only"),
            ('both', "Both", "Import both proxy and render models")
        ),
    )

    max_animation_frames: IntProperty(
        name="Max Animation Frames",
        description="The maximum number of frames to import",
        default=1000,
    )
    
    flatten: BoolProperty(
        name="Flatten",
        description="Flatten the meshes normals",
        default=True
    )

    def execute(self, context):

        options = {
            'import_type': self.import_type,
            'max_animation_frames': self.max_animation_frames,
            'flatten': self.flatten
        }

        return read_data(context, self.filepath, options)

def menu_func_import(self, context):
    self.layout.operator(MiexImport.bl_idname, text="MiEx (.usd)")

def register():
    bpy.utils.register_class(MiexImport)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)

def unregister():
    bpy.utils.unregister_class(MiexImport)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)

if __name__ == "__main__":
    register()
    # Test call (invoke the operator)
    bpy.ops.mieximport.world('INVOKE_DEFAULT')
